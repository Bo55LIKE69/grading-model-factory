# -*- coding: utf-8 -*-
"""批改回测质检：串号检测、评语去重、分数合法性、偏差统计。
用法: python sanity_check.py <评分JSON目录> [--map 映射.json] [--orig-mode filename]
来源：149 份盲评实战。三项检测缺一整批即应作废（见 pitfalls.md #28–30）。
"""
import json, os, re, sys, glob, statistics
from collections import Counter


def _fix(t):
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r',(\s*[\]\}])', r'\1', t)      # 尾随逗号
        t = re.sub(r'//[^\n]*', '', t)              # 行注释
    return t


def load(p):
    """容错 JSON 解析：正常失败时修尾随逗号/注释，再失败则暴力逐对象提取。"""
    raw = open(p, encoding='utf-8').read()
    try:
        return json.loads(raw)
    except Exception:
        pass
    t = _fix(raw)
    try:
        return json.loads(t)
    except Exception:
        out, depth, start, instr, esc = [], 0, None, False, False
        for i, ch in enumerate(t):
            if instr:
                if esc: esc = False
                elif ch == '\\': esc = True
                elif ch == '"': instr = False
                continue
            if ch == '"': instr = True
            elif ch == '{':
                if depth == 0: start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        out.append(json.loads(_fix(t[start:i + 1])))
                    except Exception:
                        pass
                    start = None
        print('  [容错] %s 暴力解析抢救 %d 个对象' % (os.path.basename(p), len(out)))
        return out


def orig_from_path(p):
    n = os.path.splitext(os.path.basename(p))[0]
    c = [int(x) for x in re.findall(r'(\d{2,3})', n) if 60 <= int(x) <= 100]
    return c[-1] if c else None


def check(items, label):
    print('\n' + '=' * 62)
    print('质检：%s（%d 条）' % (label, len(items)))
    print('=' * 62)
    if not items:
        print('  ！！！空数据集，无法质检')
        return

    # 1) 串号检测
    bad_ref, no_ev = [], []
    for x in items:
        if not isinstance(x, dict) or not x.get('id'):
            continue
        own = re.sub(r'\D', '', x['id'])          # 自身编号的数字部分，如 '01'
        s = json.dumps(x, ensure_ascii=False)
        # 只匹配图片编号形态（如 C01_p03），排除自身
        refs = sorted(set(r for r in re.findall(r'([A-Za-z]\d\d)_p\d+', s)
                          if re.sub(r'\D', '', r) != own))
        if refs:
            bad_ref.append((x['id'], refs))
        if x.get('deductions') and not any(str(d.get('evidence', '')).strip()
                                           for d in x['deductions'] if isinstance(d, dict)):
            no_ev.append(x['id'])
    print('[1] 串号检测（evidence 引用非本样本图片编号）')
    print('    污染 %d 份' % len(bad_ref), bad_ref if bad_ref else '  ✓ 通过')

    # 2) 评语去重 + 宽松口径串号（跨份提及）
    cm = Counter(x.get('comment', '') for x in items if isinstance(x, dict))
    dup = [(t[:44], n) for t, n in cm.most_common() if n > 1 and t]
    # 宽松：扣分项 evidence 里出现"其他样本的图片编号"形态（Cxx_pNN），
    # 这几乎总是证据错位；纯"对比Cxx也如此"属合理比较，不计入
    loose = []
    for x in items:
        if not isinstance(x, dict) or not x.get('id'):
            continue
        own = re.sub(r'\D', '', x['id'])
        for d in x.get('deductions', []) or []:
            if not isinstance(d, dict):
                continue
            ev = str(d.get('evidence', ''))
            hits = [r for r in re.findall(r'([A-Za-z]\d\d)_p\d+', ev)
                    if re.sub(r'\D', '', r) != own]
            if hits:
                loose.append(x['id'])
                break
    loose = sorted(set(loose))
    print('[2] 评语去重检测')
    print('    重复评语 %d 组' % len(dup), '→ %s' % dup[:3] if dup else '  ✓ 通过')
    if dup:
        print('    ⚠️ 上下文漂移铁证，该批次应作废')
    print('[2b] 宽松串号（提及非本样本编号，需人工判断是"跨份比较"还是"证据错位"）')
    print('    %d 份 %s' % (len(loose), loose[:8] if loose else '  ✓ 通过'))
    if loose:
        print('    ⚠️ 抽查这些份：若是"对比Cxx也如此"属合理比较；若 evidence 引用了别份图片即污染')

    # 3) 分数合法性
    scores = [x.get('score') for x in items if isinstance(x, dict)]
    bad_score = [x.get('id') for x in items if isinstance(x, dict)
                 and not isinstance(x.get('score'), int)]
    oob = [x.get('id') for x in items if isinstance(x, dict)
           and isinstance(x.get('score'), int) and not (65 <= x['score'] <= 96)]
    print('[3] 分数合法性')
    if scores:
        v = [s for s in scores if isinstance(s, int)]
        print('    范围 %d–%d | 非整数/空值 %d 个 %s | 越界 %d 个 %s'
              % (min(v), max(v), len(bad_score), bad_score[:5] if bad_score else '',
                 len(oob), oob[:5] if oob else ''))
    print('    %s' % ('✓ 通过' if not bad_score and not oob else '⚠️ 存在问题'))

    # 4) 证据缺失
    print('[4] 扣分证据完整性')
    print('    无 evidence 的扣分报告 %d 份 %s' % (len(no_ev), no_ev[:5] if no_ev else '  ✓ 通过'))

    verdict = '✓ 可交付' if not (bad_ref or dup or bad_score or oob or no_ev) else '⚠️ 需人工复核'
    print('\n结论：%s' % verdict)
    return {'contaminated': len(bad_ref), 'dup': len(dup), 'bad_score': len(bad_score) + len(oob)}


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(1)
    for p in args:
        items = load(p)
        if isinstance(items, dict):
            items = list(items.values())
        check(items, os.path.basename(p))
