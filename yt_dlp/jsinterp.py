import collections
import contextlib
import itertools
import json
import math
import operator
import re

import js2py

from .utils import (
    NO_DEFAULT,
    ExtractorError,
    js_to_json,
    remove_quotes,
    truncate_string,
    unified_timestamp,
    write_string,
)


def _js_bit_op(op):
    def zeroise(x):
        return 0 if x in (None, JS_Undefined) else x

    def wrapped(a, b):
        return op(zeroise(a), zeroise(b)) & 0xffffffff

    return wrapped


def _js_arith_op(op):

    def wrapped(a, b):
        if JS_Undefined in (a, b):
            return float('nan')
        return op(a or 0, b or 0)

    return wrapped


def _js_div(a, b):
    if JS_Undefined in (a, b) or not (a and b):
        return float('nan')
    return (a or 0) / b if b else float('inf')


def _js_mod(a, b):
    if JS_Undefined in (a, b) or not b:
        return float('nan')
    return (a or 0) % b


def _js_exp(a, b):
    if not b:
        return 1  # even 0 ** 0 !!
    elif JS_Undefined in (a, b):
        return float('nan')
    return (a or 0) ** b


def _js_eq_op(op):

    def wrapped(a, b):
        if {a, b} <= {None, JS_Undefined}:
            return op(a, a)
        return op(a, b)

    return wrapped


def _js_comp_op(op):

    def wrapped(a, b):
        if JS_Undefined in (a, b):
            return False
        if isinstance(a, str) or isinstance(b, str):
            return op(str(a or 0), str(b or 0))
        return op(a or 0, b or 0)

    return wrapped


def _js_ternary(cndn, if_true=True, if_false=False):
    """Simulate JS's ternary operator (cndn?if_true:if_false)"""
    if cndn in (False, None, 0, '', JS_Undefined):
        return if_false
    with contextlib.suppress(TypeError):
        if math.isnan(cndn):  # NB: NaN cannot be checked by membership
            return if_false
    return if_true


# Ref: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/Operator_Precedence
_OPERATORS = {  # None => Defined in JSInterpreter._operator
    '?': None,
    '??': None,
    '||': None,
    '&&': None,

    '|': _js_bit_op(operator.or_),
    '^': _js_bit_op(operator.xor),
    '&': _js_bit_op(operator.and_),

    '===': operator.is_,
    '!==': operator.is_not,
    '==': _js_eq_op(operator.eq),
    '!=': _js_eq_op(operator.ne),

    '<=': _js_comp_op(operator.le),
    '>=': _js_comp_op(operator.ge),
    '<': _js_comp_op(operator.lt),
    '>': _js_comp_op(operator.gt),

    '>>': _js_bit_op(operator.rshift),
    '<<': _js_bit_op(operator.lshift),

    '+': _js_arith_op(operator.add),
    '-': _js_arith_op(operator.sub),

    '*': _js_arith_op(operator.mul),
    '%': _js_mod,
    '/': _js_div,
    '**': _js_exp,
}

_COMP_OPERATORS = {'===', '!==', '==', '!=', '<=', '>=', '<', '>'}

_NAME_RE = r'[a-zA-Z_$][\w$]*'
_MATCHING_PARENS = dict(zip(*zip('()', '{}', '[]')))
_QUOTES = '\'"/'


class JS_Undefined:
    pass


class JS_Break(ExtractorError):
    def __init__(self):
        ExtractorError.__init__(self, 'Invalid break')


class JS_Continue(ExtractorError):
    def __init__(self):
        ExtractorError.__init__(self, 'Invalid continue')


class JS_Throw(ExtractorError):
    def __init__(self, e):
        self.error = e
        ExtractorError.__init__(self, f'Uncaught exception {e}')


class LocalNameSpace(collections.ChainMap):
    def __setitem__(self, key, value):
        for scope in self.maps:
            if key in scope:
                scope[key] = value
                return
        self.maps[0][key] = value

    def __delitem__(self, key):
        raise NotImplementedError('Deleting is not supported')


class Debugger:
    import sys
    ENABLED = False and 'pytest' in sys.modules

    @staticmethod
    def write(*args, level=100):
        write_string(f'[debug] JS: {"  " * (100 - level)}'
                     f'{" ".join(truncate_string(str(x), 50, 50) for x in args)}\n')

    @classmethod
    def wrap_interpreter(cls, f):
        def interpret_statement(self, stmt, local_vars, allow_recursion, *args, **kwargs):
            if cls.ENABLED and stmt.strip():
                cls.write(stmt, level=allow_recursion)
            try:
                ret, should_ret = f(self, stmt, local_vars, allow_recursion, *args, **kwargs)
            except Exception as e:
                if cls.ENABLED:
                    if isinstance(e, ExtractorError):
                        e = e.orig_msg
                    cls.write('=> Raises:', e, '<-|', stmt, level=allow_recursion)
                raise
            if cls.ENABLED and stmt.strip():
                cls.write(['->', '=>'][should_ret], repr(ret), '<-|', stmt, level=allow_recursion)
            return ret, should_ret
        return interpret_statement


class JSInterpreter:

    _RE_FLAGS = {
        # special knowledge: Python's re flags are bitmask values, current max 128
        # invent new bitmask values well above that for literal parsing
        # TODO: new pattern class to execute matches with these flags
        'd': 1024,  # Generate indices for substring matches
        'g': 2048,  # Global search
        'i': re.I,  # Case-insensitive search
        'm': re.M,  # Multi-line search
        's': re.S,  # Allows . to match newline characters
        'u': re.U,  # Treat a pattern as a sequence of unicode code points
        'y': 4096,  # Perform a "sticky" search that matches starting at the current position in the target string
    }

    _EXC_NAME = '__yt_dlp_exception__'

    def __init__(self, code, objects=None):
        self.code, self._functions = code, {}
        self.ctx = js2py.EvalJs(objects or {})
        self.ctx.execute(code)

    class Exception(ExtractorError):
        def __init__(self, msg, expr=None, *args, **kwargs):
            if expr is not None:
                msg = f'{msg.rstrip()} in: {truncate_string(expr, 50, 50)}'
            super().__init__(msg, *args, **kwargs)

    @classmethod
    def _regex_flags(cls, expr):
        flags = 0
        if not expr:
            return flags, expr
        for idx, ch in enumerate(expr):
            if ch not in cls._RE_FLAGS:
                break
            flags |= cls._RE_FLAGS[ch]
        return flags, expr[idx + 1:]

    @staticmethod
    def _separate(expr, delim=',', max_split=None):
        OP_CHARS = '+-*/%&|^=<>!,;{}:'
        if not expr:
            return
        counters = {k: 0 for k in _MATCHING_PARENS.values()}
        start, splits, pos, delim_len = 0, 0, 0, len(delim) - 1
        in_quote, escaping, after_op, in_regex_char_group = None, False, True, False
        for idx, char in enumerate(expr):
            if not in_quote and char in _MATCHING_PARENS:
                counters[_MATCHING_PARENS[char]] += 1
            elif not in_quote and char in counters:
                counters[char] -= 1
            elif not escaping:
                if char in _QUOTES and in_quote in (char, None):
                    if in_quote or after_op or char != '/':
                        in_quote = None if in_quote and not in_regex_char_group else char
                elif in_quote == '/' and char in '[]':
                    in_regex_char_group = char == '['
            escaping = not escaping and in_quote and char == '\\'
            after_op = not in_quote and char in OP_CHARS or (char.isspace() and after_op)

            if char != delim[pos] or any(counters.values()) or in_quote:
                pos = 0
                continue
            elif pos != delim_len:
                pos += 1
                continue
            yield expr[start: idx - delim_len]
            start, pos = idx + 1, 0
            splits += 1
            if max_split and splits >= max_split:
                break
        yield expr[start:]

    @classmethod
    def _separate_at_paren(cls, expr, delim=None):
        if delim is None:
            delim = expr and _MATCHING_PARENS[expr[0]]
        separated = list(cls._separate(expr, delim, 1))
        if len(separated) < 2:
            raise cls.Exception(f'No terminating paren {delim}', expr)
        return separated[0][1:].strip(), separated[1].strip()

    def extract_object(self, objname):
        return getattr(self.ctx, objname)

    def extract_function(self, funcname):
        return getattr(self.ctx, funcname)

    def call_function(self, funcname, *args):
        return self.extract_function(funcname)(args)
