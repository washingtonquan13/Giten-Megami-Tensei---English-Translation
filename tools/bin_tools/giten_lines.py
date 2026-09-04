"""Player-visible text lines out of a decoded Giten script -- thin wrapper.

The span detection this script pioneered now lives in ``tools/giten/spans.py``,
where the real extractor uses it; this file keeps the original ad-hoc listing
behaviour for quick eyeballing.  Tags:
  1FD0 window/narration open   1FBA narration line     1FD2 speaker name
  1FD3 speech line             1FB1 open choice list   1FB2 choice option
  1FB7 close choice list       1FD1 close window       1FFA/1FFB styled run
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.giten import dictionary as _dictionary       # noqa: E402
from tools.giten import framing as _framing             # noqa: E402
from tools.giten import spans as _spans                 # noqa: E402
from giten_text import dictionary, render               # noqa: E402,F401

JP = re.compile(r'[぀-ヿ一-鿿]')


def lines(buf, expand=True):
    """[(offset, tag, text)] for every text span in a decoded body."""
    dic = _dictionary.load() if expand else None
    frame = _framing.Frame(index=0, rec_id=None, data_start=0,
                           data_end=len(buf), kind='flat')
    return [(sp.start, sp.tag, _spans.span_text(buf, sp, dic))
            for sp in _spans.scan_frame(buf, frame, dic)]


if __name__ == '__main__':
    from tools.giten import container, paths
    p = sys.argv[1]
    if os.path.exists(p) and os.sep + 'decoded' + os.sep in os.path.abspath(p):
        b = open(p, 'rb').read()
    else:
        src = p if os.path.isabs(p) else os.path.join(paths.game_root(),
                                                      *p.split('/'))
        _hdr, b = container.unpack(open(src, 'rb').read())
    for o, t, s in lines(b):
        if '--jp' in sys.argv and not JP.search(s):
            continue
        print("%06x %s  %s" % (o, t, s))
