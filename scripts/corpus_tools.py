# -*- coding: utf-8 -*-
"""批改语料工具：从提取的 md 构建分数-评语语料表并做统计

用法:
  python corpus_tools.py build <md目录> <输出.tsv> [manifest.tsv]
  python corpus_tools.py analyze <语料.tsv>

阶段3「批改载体探测」后，按《载体探测报告》修改下方 CONFIG：
- grade_words / doc_score / doc_comment / merged_comment: 文内批改区定位与提取正则
- fn_score_range: 文件名分数的合理区间（百分制默认 40-100）
- bands: 分段边界（从高到低）
- keywords: 评语关键词（按语料特征增删）
"""
import re
import os
import io
import sys
import collections

CONFIG = {
    # ---- 文内批改区定位（含空格变体「成 绩」）----
    "grade_words": r"成\s*绩|评\s*语|得分|分数|等级",
    # ---- 文内分数（按顺序尝试，取首个落在区间内的匹配）----
    "doc_score": [
        r"成\s*绩[：:评\s]{0,4}(\d{2,3})",
        r"(\d{2,3})\s*[，,。]",
    ],
    # ---- 文内评语 ----
    "doc_comment": r"评\s*语[：:]\s*(.{2,80})",
    # ---- 合并式：成绩与评语同格（如「成绩：82，缺总结。」）----
    "merged_comment": r"成\s*绩[：:][^，,。]{0,6}[，,]\s*(.{2,80})",
    # ---- 文件名分数：取第一个中文字符之后的数字组中，最后一个落在区间内的 ----
    # （学号在文件名前部、教师追加的分数在后部；规避学号与批次标签误判）
    "fn_score_range": (40, 100),
    # ---- 分段边界（从高到低）----
    "bands": [(95, "95+"), (90, "90-94"), (85, "85-89"), (80, "80-84"), (75, "75-79"), (0, "<75")],
    # ---- 评语关键词（高频维度统计用）----
    "keywords": [
        "缺总结", "缺心得", "认真", "有思考", "有创意", "有想法", "个别有误", "有个别",
        "错误", "错了", "不对", "格式", "截图", "较小", "太小", "偏大", "美观", "清晰",
        "第9", "坐标系", "附加题", "缺附加", "漏做", "未按要求", "未完全", "复现", "雷同",
        "一样", "封面", "模板", "总结较", "总结到", "过程", "较详细", "较简洁", "较简单",
        "简单", "文图不对应", "错别字", "建库", "入库", "结果图", "选做", "设计", "不错",
        "较好", "很好", "基本按", "完全按", "不规范", "图例", "配色", "亮点", "思考",
    ],
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def clean(t):
    t = re.sub(r"\{[^}]*\}", "", t)          # pandoc 属性 {.underline} {.comment-start}
    t = re.sub(r"\[|\]", "", t)              # 方括号
    t = t.replace("**", "").replace("\\", " ")
    t = re.sub(r"^\s*L\d+:\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fn_score(name):
    """文件名分数：第一个中文字符之后、最后一个落在合理区间的数字组"""
    m = CJK_RE.search(name)
    part = name[m.start():] if m else name
    lo, hi = CONFIG["fn_score_range"]
    groups = [int(g) for g in re.findall(r"\d+", part)]
    in_range = [g for g in groups if lo <= g <= hi]
    return in_range[-1] if in_range else None


def doc_extract(lines):
    """文内分数与评语提取（含字段互换纠偏）。返回 (score, comment)。"""
    hits = [i for i, l in enumerate(lines) if re.search(CONFIG["grade_words"], l)]
    if not hits:
        return None, ""
    ctx = CONFIG["grade_words"] + r"|^[\d\s\.\,，。；;、\|\[\]]+$|^[^a-zA-Z\d]{0,6}$"
    taken, block = set(), []
    for i in hits[:6]:
        for j in range(max(0, i - 1), min(len(lines), i + 3)):
            if j not in taken and (j == i or re.search(ctx, lines[j])):
                taken.add(j)
                block.append(lines[j])
    txt = clean(" ".join(block[:8]))

    score = None
    cands = []
    for pat in CONFIG["doc_score"]:
        cands += re.findall(pat, txt)
    for c in cands:
        v = int(c)
        if CONFIG["fn_score_range"][0] <= v <= CONFIG["fn_score_range"][1]:
            score = v
            break

    comment = ""
    m = re.search(CONFIG["doc_comment"], txt)
    if m:
        comment = m.group(1).strip(" ，。")
    else:
        m2 = re.search(CONFIG["merged_comment"], txt)
        if m2:
            comment = m2.group(1).strip(" ，。")
    # 字段互换纠偏：评语是纯数字 → 真评语可能在"成绩："后面
    if comment and re.fullmatch(r"\d{2,3}", comment.strip()):
        comment = ""
        m3 = re.search(r"成\s*绩[：:]\s*([^\d].{1,60})", txt)
        if m3:
            comment = m3.group(1).strip(" ，。")
    return score, comment


def build(md_dir, out_tsv, manifest_path=None):
    manifest = {}
    if manifest_path and os.path.exists(manifest_path):
        with io.open(manifest_path, encoding="utf-8-sig") as f:
            next(f, None)
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    manifest[parts[0]] = parts[2]
    rows = []
    for fn in sorted(os.listdir(md_dir)):
        if not fn.endswith(".md"):
            continue
        f = fn_score(fn[:-3])
        with io.open(os.path.join(md_dir, fn), encoding="utf-8", errors="ignore") as fh:
            lines = fh.read().splitlines()
        d, c = doc_extract(lines)
        score = d if d is not None else f
        rows.append([
            manifest.get(fn, ""), fn[:-3],
            "" if f is None else f, "" if d is None else d,
            "" if score is None else score, c,
        ])
    with io.open(out_tsv, "w", encoding="utf-8-sig", newline="\n") as fh:
        fh.write("batch\tfile\tfn_score\tdoc_score\tscore\tcomment\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    n_score = sum(1 for r in rows if r[4] != "")
    n_com = sum(1 for r in rows if r[5])
    print("总文件 %d | 有分数 %d (提取率 %.0f%%) | 有评语 %d" % (
        len(rows), n_score, 100.0 * n_score / max(1, len(rows)), n_com))


def band_of(s):
    s = int(s)
    for cut, label in CONFIG["bands"]:
        if s >= cut:
            return label
    return CONFIG["bands"][-1][1]


def analyze(tsv):
    with io.open(tsv, encoding="utf-8-sig") as f:
        next(f, None)
        rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
    scored = [r for r in rows if len(r) >= 6 and r[4] != ""]
    withcom = [r for r in scored if r[5]]
    print("总文件 %d | 有分数 %d | 有评语 %d" % (len(rows), len(scored), len(withcom)))

    # 分数与文件名分一致性
    both = [r for r in rows if len(r) >= 6 and r[2] != "" and r[3] != ""]
    agree = sum(1 for r in both if r[2] == r[3])
    if both:
        print("文件名分 vs 文内分: 两者都有 %d 份, 一致 %d 份 (%.0f%%)" % (
            len(both), agree, 100.0 * agree / len(both)))

    # 分段评语
    bands = collections.defaultdict(list)
    for r in withcom:
        bands[band_of(r[4])].append((int(r[4]), r[5]))
    for cut, label in CONFIG["bands"]:
        lst = sorted(bands.get(label, []))
        shown = lst[:50]
        print("\n===== %s（%d 条评语%s）=====" % (
            label, len(lst), "，仅显示前50" if len(lst) > 50 else ""))
        for s, c in shown:
            print("%d | %s" % (s, c))

    # 评语长度
    if withcom:
        lens = sorted(len(r[5]) for r in withcom)
        print("\n===== 评语长度 =====")
        print("最短 %d | 中位 %d | 平均 %.0f | 最长 %d" % (
            lens[0], lens[len(lens) // 2], sum(lens) / len(lens), lens[-1]))

    # 关键词频率
    allc = " ".join(r[5] for r in withcom)
    print("\n===== 关键词频率 =====")
    for k in CONFIG["keywords"]:
        n = allc.count(k)
        if n:
            print("%s: %d" % (k, n))

    # 高频二字组（自动发现课程特有关键词）
    bigrams = collections.Counter()
    for r in withcom:
        c = r[5]
        for i in range(len(c) - 1):
            bg = c[i:i + 2]
            if CJK_RE.match(bg[0]) and CJK_RE.match(bg[1]):
                bigrams[bg] += 1
    print("\n===== 评语高频二字组（前30，用于补充关键词）=====")
    for bg, n in bigrams.most_common(30):
        print("%s: %d" % (bg, n))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "build" and len(sys.argv) >= 4:
        md_dir, out_tsv = sys.argv[2], sys.argv[3]
        man = sys.argv[4] if len(sys.argv) > 4 else None
        build(md_dir, out_tsv, man)
    elif cmd == "analyze" and len(sys.argv) >= 3:
        analyze(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
