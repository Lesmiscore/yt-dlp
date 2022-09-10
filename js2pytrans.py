# mini PoC to tinker with js2py

import sys
import os
import re
import subprocess
import json

from js2py import EvalJs
from js2py.base import to_python
from js2py.translators import translate_js

from yt_dlp.utils import unified_timestamp

def unitime(value):
    return int(unified_timestamp(to_python(value)) * 1e3)

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


if False:
    TESTS = [
        "1969-12-31T16:00:40.000-08:00",
        "Thursday 01 January 1970 00:00:05 UTC",
        "1969-12-31T20:00:53.000-04:00",
        "01 January 1970 00:01:21 UTC",
        "December 31 1969 13:45:41 -1015",
        "01/01/1970 00:00:07 GMT",
        "December 31 1969 20:00:53 EDT",
        "1969-12-31T19:01:28.000-05:00",
        "Wednesday December 31 1969 19:00:14 CDT",
    ]

    for tst in TESTS:
        with subprocess.Popen(
            ['node', '-e', f'console.log(new Date({json.dumps(tst)})/1e3)'],
            stdout=subprocess.PIPE) as proc:
            nodejs = int(proc.stdout.read().decode())
        ytdlp = unified_timestamp(tst)
        print(f'{tst}: nodejs {nodejs} yt-dlp {ytdlp} okay {nodejs == ytdlp}')


infile = sys.argv[1]
transfile = infile + '.translated.py'
with open(infile, 'rt') as r, open(transfile, 'wt') as w:
    if infile.endswith('.py'):
        os.unlink(transfile)
        translated = r.read()
        transfile = infile
    else:
        code = r.read()
        code = re.sub(r'catch\s*\((.)\)\s*{', r'catch(\1){print(\1.toString());', code)
        # code = re.sub(r'catch\s*\((.)\)\s*{', r'catch(\1){throw \1;', code)

        # code = re.sub(r'try\s*{', r'{', code)
        # code = re.sub(r'catch\s*\((.)\)\s*{', r'if(false){', code)
        # code = re.sub(r'finally\s*{', r'{', code)

        translated = translate_js(code, '')
        w.write(translated)

    exec(compile(translated, transfile, 'exec'), ctx._context)
