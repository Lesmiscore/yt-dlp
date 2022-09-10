# mini PoC to tinker with js2py

import sys
import re

from js2py import EvalJs
from js2py.base import to_python
from js2py.translators import translate_js

from yt_dlp.utils import unified_timestamp

# with open(sys.argv[1], 'rt') as r, open(sys.argv[1] + '.translated.py', 'wt') as w:
#     w.write(translate_js(r.read(), ''))

def unitime(value):
    return unified_timestamp(to_python(value))

ctx = EvalJs({
    '_ytdlp_unified_timestamp': unitime,
    'print': print,
})

ctx._context['var'].own['Date'].update({
    # force update the flags here to do the magic below
    'writable': True,
    'enumerable': False,
    'configurable': True,
})

ctx.execute('''
    // https://developer.mozilla.org/docs/Web/JavaScript/Reference/Global_Objects/Object/assign

    Object.assign = function _assign(target, varArgs) { // .length of function is 2
        'use strict';
        if (target === null || target === undefined) {
            throw new TypeError('Cannot convert undefined or null to object');
        }

        var to = Object(target);

        for (var index = 1; index < arguments.length; index++) {
            var nextSource = arguments[index];

            if (nextSource !== null && nextSource !== undefined) {
                for (var nextKey in nextSource) {
                    // Avoid bugs when hasOwnProperty is shadowed
                    if (Object.prototype.hasOwnProperty.call(nextSource, nextKey)) {
                    to[nextKey] = nextSource[nextKey];
                    }
                }
            }
        }
        return to;
    }

    // we'll patch Date constructor to pass it an acceptable (to js2py, not by spec) value
    const _origDate = Date;
    window.Date = function Date(){
        if (!(this instanceof Date)) {
            // called as function
            return _origDate();
        }
        if(arguments.length !== 1){
            _origDate.apply(this, arguments);
            return;
        }
        // use the host's great datetime parser!
        _origDate.call(this, _ytdlp_unified_timestamp(arguments[0]));
    };
''')


transfile = sys.argv[1] + '.translated.py'
with open(sys.argv[1], 'rt') as r, open(transfile, 'wt') as w:
    code = r.read()
    # code = re.sub(r'catch\s*\((.)\)\s*{', r'catch(\1){print(\1.toString());', code)
    # code = re.sub(r'catch\s*\((.)\)\s*{', r'catch(\1){throw \1;', code)

    code = re.sub(r'try\s*{', r'{', code)
    code = re.sub(r'catch\s*\((.)\)\s*{', r'if(false){', code)
    code = re.sub(r'finally\s*{', r'{', code)

    translated = translate_js(code, '')
    w.write(translated)
    exec(compile(translated, transfile, 'exec'), ctx._context)
