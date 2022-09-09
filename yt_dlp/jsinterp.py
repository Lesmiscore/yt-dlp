import re
import js2py

from .utils import (
    ExtractorError,
    truncate_string,
)


_MATCHING_PARENS = dict(zip(*zip('()', '{}', '[]')))
_QUOTES = '\'"/'


class JSInterpreter:

    def __init__(self, code, objects=None):
        self.code = code
        self.ctx = js2py.EvalJs(objects or {})

        try:
            self.ctx.execute(code)
        except js2py.PyJsException as e:
            raise self.Exception(e.message, cause=e)

    class Exception(ExtractorError):
        def __init__(self, msg, expr=None, *args, **kwargs):
            if expr is not None:
                msg = f'{msg.rstrip()} in: {truncate_string(expr, 50, 50)}'
            super().__init__(msg, *args, **kwargs)

    def extract_object(self, objname):
        return getattr(self.ctx, objname)

    def extract_function(self, funcname):
        return getattr(self.ctx, funcname)

    def call_function(self, funcname, *args):
        try:
            return self.extract_function(funcname)(args)
        except js2py.PyJsException as e:
            raise self.Exception(e.message, cause=e)
