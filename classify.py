"""Classify forum comments with Cloudflare's Clef model and build an HTML review page.

Usage:
    python3 classify.py                 # classify all comments with "clef", write results.json + results.html
    python3 classify.py --model clef-flash
    python3 classify.py --html-only     # rebuild results.html from results.json (no API calls)

Credentials are read from cloud-flare.local.sh (never committed; see .gitignore).
Standard library only: no pip install needed.
"""

import argparse
import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

LABELS = ["acceptable", "toxic", "spam"]

# The question we put to Clef. The wording of the criteria is the main lever on accuracy:
# each option says what it covers AND what it does not, so that blunt-but-fair posts
# are not flagged as toxic and helpful links are not flagged as spam.
QUESTION = {
    "type": "choice",
    "instructions": (
        "You are moderating the discussion forum of an online college course on applied AI, "
        "taken by engineering students in India. Students ask doubts, share projects, give "
        "feedback and chat; informal English, Hinglish and emojis are normal. "
        "Classify `comment`, posted by `author` in the forum thread `thread`. "
        "Judge what the post does, not its tone alone: criticism of work, grading or the course "
        "is allowed; attacking people is not; promotion and scams are not."
    ),
    "criteria": {
        "acceptable": (
            "A normal student or staff post: a question, answer, tip, project share, feedback "
            "(including blunt criticism of someone's work, the assignment, the grading or the "
            "course), disagreement, a complaint or request to teachers, thanks, an apology, "
            "or casual chat. Choose this unless the post clearly fits toxic or spam."
        ),
        "toxic": (
            "Targets a person or group rather than ideas or work: insults, name-calling, mocking "
            "or humiliating someone, telling them to leave, harassment, threats or intimidation, "
            "or demeaning remarks about a group (gender, region, caste, religion, branch, etc.)."
        ),
        "spam": (
            "Unsolicited promotion or a scam that is not a genuine contribution to the course "
            "discussion: ads for products or services, paid assignment help or solutions, "
            "selling notes or leaked papers, money-making or crypto schemes, follower or "
            "referral offers, giveaways, or links and contact numbers pushed for someone's gain."
        ),
    },
}


def read_credentials(path="cloud-flare.local.sh"):
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        sys.exit(f"Missing {path}. Copy cloud-flare.sh to {path} and fill in your account ID and token.")
    creds = dict(re.findall(r'export (\w+)="([^"]*)"', text))
    for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        if not creds.get(key):
            sys.exit(f"{key} not found in {path}. Values must be inside double quotes.")
    return creds["CLOUDFLARE_ACCOUNT_ID"], creds["CLOUDFLARE_API_TOKEN"]


def classify(comment, account, token, model, retries=6):
    """Ask Clef one question about one comment. Retries on rate limits and server errors."""
    payload = {
        "state": {
            "comment": comment["comment"],
            "author": comment["author"],
            "thread": comment["thread"],
        },
        "questions": {"label": QUESTION},
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.load(response)
            if not data.get("success"):
                raise RuntimeError(data.get("errors"))
            answer = data["result"]["answers"]["label"]
            return {
                "label": answer["choice"],
                "confidence": answer.get("confidence"),
                "probabilities": answer.get("probabilities", {}),
            }
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                sys.exit(f"HTTP {err.code}: Cloudflare rejected the account ID or token.")
            if err.code == 429 or err.code >= 500:
                time.sleep(2 ** attempt)  # back off and retry
                continue
            raise RuntimeError(f"HTTP {err.code}: {err.read().decode()[:300]}")
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Comment {comment['id']}: gave up after {retries} attempts")


def run(model):
    data = json.load(open("comments.json", encoding="utf-8"))
    comments = data["comments"]
    account, token = read_credentials()
    print(f"Classifying {len(comments)} comments with {model} ...")

    done = 0
    lock = threading.Lock()

    def work(c):
        nonlocal done
        result = classify(c, account, token, model)
        with lock:
            done += 1
            print(f"  [{done:3}/{len(comments)}] #{c['id']:<3} {result['label']:<10} "
                  f"(confidence {result['confidence']:.2f})", flush=True)
        return {**c, **result}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, comments))

    output = {
        "model": model,
        "course": data.get("course"),
        "forum": data.get("forum"),
        "question": QUESTION,
        "results": results,
    }
    json.dump(output, open("results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Wrote results.json")
    return output


# ---------------------------------------------------------------- HTML page

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clef moderation review</title>
<style>
  :root {
    --bg: #f6f5f1; --card: #ffffff; --ink: #1d1d1b; --muted: #6b6a66; --line: #e3e1da;
    --ok: #2f7d4f; --ok-bg: #e6f2ea; --tox: #b3261e; --tox-bg: #fbe7e5;
    --spam: #9a6200; --spam-bg: #fdf1dc; --flag: #3b4fd8; --flag-bg: #e9ecfc;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #161614; --card: #20201d; --ink: #ecebe6; --muted: #9b9a94; --line: #34332f;
      --ok: #7fcf9d; --ok-bg: #1e3326; --tox: #ff8f86; --tox-bg: #3d1f1c;
      --spam: #f0be63; --spam-bg: #3a2c12; --flag: #9aa8ff; --flag-bg: #23284a;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  header { padding: 28px 20px 8px; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--muted); margin: 0; }
  .stats { display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0 6px; }
  .stat { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
          padding: 10px 14px; min-width: 120px; }
  .stat b { display: block; font-size: 22px; }
  .stat span { color: var(--muted); font-size: 13px; }
  .bar { position: sticky; top: 0; z-index: 2; background: var(--bg);
         border-bottom: 1px solid var(--line); }
  .controls { max-width: 1100px; margin: 0 auto; padding: 10px 20px;
              display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .controls button, .controls select, .controls input {
    font: inherit; border: 1px solid var(--line); background: var(--card); color: var(--ink);
    border-radius: 999px; padding: 6px 14px; cursor: pointer; }
  .controls input { cursor: text; border-radius: 8px; flex: 1; min-width: 160px; }
  .controls button.on { background: var(--ink); color: var(--bg); border-color: var(--ink); }
  main { max-width: 1100px; margin: 0 auto; padding: 14px 20px 60px; }
  .row { display: grid; grid-template-columns: 56px 1fr 190px; gap: 14px;
         background: var(--card); border: 1px solid var(--line); border-left: 5px solid var(--line);
         border-radius: 10px; padding: 12px 14px; margin-bottom: 8px; }
  .row.acceptable { border-left-color: var(--ok); }
  .row.toxic { border-left-color: var(--tox); }
  .row.spam { border-left-color: var(--spam); }
  .row.flagged { outline: 2px solid var(--flag); }
  .id { font-weight: 700; color: var(--muted); font-variant-numeric: tabular-nums; }
  .meta { color: var(--muted); font-size: 13px; margin-bottom: 2px; }
  .text { white-space: pre-wrap; word-break: break-word; }
  .badge { display: inline-block; font-weight: 700; font-size: 12px; letter-spacing: .04em;
           text-transform: uppercase; padding: 3px 10px; border-radius: 999px; }
  .badge.acceptable { color: var(--ok); background: var(--ok-bg); }
  .badge.toxic { color: var(--tox); background: var(--tox-bg); }
  .badge.spam { color: var(--spam); background: var(--spam-bg); }
  .probs { margin-top: 8px; font-size: 12px; color: var(--muted); }
  .p { display: grid; grid-template-columns: 70px 1fr 34px; gap: 6px; align-items: center; }
  .track { height: 6px; border-radius: 3px; background: var(--line); overflow: hidden; }
  .fill { height: 100%; }
  .fill.acceptable { background: var(--ok); } .fill.toxic { background: var(--tox); }
  .fill.spam { background: var(--spam); }
  .low { display: inline-block; margin-left: 6px; font-size: 11px; font-weight: 700;
         color: var(--flag); background: var(--flag-bg); border-radius: 999px; padding: 2px 8px; }
  .review { grid-column: 2 / 4; display: none; gap: 8px; flex-wrap: wrap; align-items: flex-start;
            border-top: 1px dashed var(--line); padding-top: 10px; }
  .row.open .review { display: flex; }
  .review select, .review textarea { font: inherit; color: var(--ink); background: var(--bg);
            border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; }
  .review textarea { flex: 1; min-width: 220px; min-height: 58px; }
  .review label { font-size: 13px; color: var(--muted); display: flex; gap: 6px; align-items: center; }
  .flagbtn { margin-top: 8px; font: inherit; font-size: 12px; border: 1px solid var(--line);
             background: transparent; color: var(--muted); border-radius: 999px;
             padding: 3px 10px; cursor: pointer; }
  .row.flagged .flagbtn { color: var(--flag); border-color: var(--flag); }
  .empty { color: var(--muted); text-align: center; padding: 40px; }
  dialog { max-width: 760px; width: 92vw; border: 1px solid var(--line); border-radius: 12px;
           background: var(--card); color: var(--ink); }
  dialog textarea { width: 100%; height: 50vh; font: 13px/1.45 ui-monospace, monospace;
           background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 8px; }
  @media (max-width: 700px) {
    .row { grid-template-columns: 40px 1fr; }
    .side { grid-column: 2; }
    .review { grid-column: 1 / 3; }
  }
</style>
</head>
<body>
<header>
  <h1>Clef moderation review</h1>
  <p class="sub">__SUBTITLE__</p>
  <div class="stats" id="stats"></div>
</header>
<div class="bar"><div class="controls">
  <button data-f="all" class="on">All</button>
  <button data-f="acceptable">Acceptable</button>
  <button data-f="toxic">Toxic</button>
  <button data-f="spam">Spam</button>
  <button data-f="low">Low confidence</button>
  <button data-f="flagged">Flagged by me</button>
  <select id="sort">
    <option value="id">Sort: comment id</option>
    <option value="conf">Sort: least confident first</option>
  </select>
  <input id="q" type="search" placeholder="Search text or author">
  <button id="export">Export MISTAKES.md</button>
</div></div>
<main id="list"></main>
<dialog id="dlg">
  <p><b>MISTAKES.md</b> — built from the comments you flagged. Copy it into the file.</p>
  <textarea id="md" readonly></textarea>
  <p><button id="copy">Copy</button> <button id="close">Close</button></p>
</dialog>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const LABELS = ['acceptable', 'toxic', 'spam'];
const LOW = __LOW__;
const KEY = 'clef-review-v1';
let review = {};
try { review = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(review)); } catch (e) {} };
let filter = 'all';
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function stats() {
  const n = l => DATA.results.filter(r => r.label === l).length;
  const low = DATA.results.filter(r => r.confidence < LOW).length;
  const flagged = Object.values(review).filter(v => v.flag).length;
  document.getElementById('stats').innerHTML =
    [['Comments', DATA.results.length], ['Acceptable', n('acceptable')], ['Toxic', n('toxic')],
     ['Spam', n('spam')], ['Low confidence', low], ['Flagged by me', flagged]]
    .map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
}

function render() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  let rows = DATA.results.filter(r => {
    if (filter === 'low') { if (!(r.confidence < LOW)) return false; }
    else if (filter === 'flagged') { if (!(review[r.id] && review[r.id].flag)) return false; }
    else if (filter !== 'all' && r.label !== filter) return false;
    return !q || (r.comment + ' ' + r.author).toLowerCase().includes(q);
  });
  if (document.getElementById('sort').value === 'conf')
    rows = rows.slice().sort((a, b) => a.confidence - b.confidence);
  document.getElementById('list').innerHTML = rows.length ? rows.map(r => {
    const rv = review[r.id] || {};
    const probs = LABELS.map(l => {
      const p = (r.probabilities[l] || 0);
      return `<div class="p"><span>${l}</span><div class="track"><div class="fill ${l}" style="width:${(p*100).toFixed(0)}%"></div></div><span>${p.toFixed(2)}</span></div>`;
    }).join('');
    const opts = LABELS.map(l => `<option ${rv.label === l ? 'selected' : ''}>${l}</option>`).join('');
    return `<article class="row ${r.label} ${rv.flag ? 'flagged open' : ''}" data-id="${r.id}">
      <div class="id">#${r.id}</div>
      <div><div class="meta">${esc(r.author)} · ${esc(r.thread)} · ${esc(r.posted_at)}</div>
        <div class="text">${esc(r.comment)}</div></div>
      <div class="side"><span class="badge ${r.label}">${r.label}</span>${r.confidence < LOW ? '<span class="low">unsure</span>' : ''}
        <div class="probs">${probs}<div>confidence ${r.confidence.toFixed(2)}</div></div>
        <button class="flagbtn">${rv.flag ? '✓ flagged' : 'Flag as mistake'}</button></div>
      <div class="review">
        <label>Right label <select class="rl">${opts}</select></label>
        <label><input type="checkbox" class="bd" ${rv.borderline ? 'checked' : ''}> borderline</label>
        <textarea class="why" placeholder="Why is Clef wrong? (1-2 sentences)">${esc(rv.why || '')}</textarea>
      </div></article>`;
  }).join('') : '<p class="empty">No comments match.</p>';
  stats();
}

document.querySelectorAll('[data-f]').forEach(b => b.onclick = () => {
  document.querySelectorAll('[data-f]').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); filter = b.dataset.f; render();
});
document.getElementById('sort').onchange = render;
document.getElementById('q').oninput = render;
const list = document.getElementById('list');
list.addEventListener('click', e => {
  if (!e.target.classList.contains('flagbtn')) return;
  const id = e.target.closest('.row').dataset.id;
  const r = DATA.results.find(x => String(x.id) === id);
  review[id] = review[id] || { label: LABELS.find(l => l !== r.label) };
  review[id].flag = !review[id].flag;
  save(); render();
});
list.addEventListener('input', e => {
  const row = e.target.closest('.row'); if (!row) return;
  const rv = review[row.dataset.id] = review[row.dataset.id] || {};
  if (e.target.classList.contains('rl')) rv.label = e.target.value;
  if (e.target.classList.contains('bd')) rv.borderline = e.target.checked;
  if (e.target.classList.contains('why')) rv.why = e.target.value;
  save();
});
document.getElementById('export').onclick = () => {
  const items = DATA.results.filter(r => review[r.id] && review[r.id].flag);
  let md = '# Mistakes in Clef\\'s classifications\\n\\n';
  md += items.length ? items.map(r => {
    const rv = review[r.id];
    return `## Comment ${r.id}${rv.borderline ? ' (borderline)' : ''}\\n\\n` +
      `> ${r.comment.replace(/\\n/g, ' ')}\\n\\n` +
      `- **Clef:** ${r.label} · **Correct:** ${rv.label}\\n` +
      `- **Why:** ${rv.why || ''}\\n`;
  }).join('\\n') : '_No mistakes flagged yet._\\n';
  document.getElementById('md').value = md;
  document.getElementById('dlg').showModal();
};
document.getElementById('copy').onclick = () => {
  const t = document.getElementById('md'); t.select();
  try { navigator.clipboard.writeText(t.value); } catch (e) { document.execCommand('copy'); }
};
document.getElementById('close').onclick = () => document.getElementById('dlg').close();
render();
</script>
</body>
</html>
"""

LOW_CONFIDENCE = 0.5


def write_html(output, path="results.html"):
    subtitle = (f"{len(output['results'])} comments from “{output.get('forum') or 'the course forum'}”, "
                f"classified by Cloudflare <b>{html.escape(output['model'])}</b>. "
                f"Answers with confidence below {LOW_CONFIDENCE} are marked “unsure”.")
    data = json.dumps(output, ensure_ascii=False).replace("</", "<\\/")
    page = (PAGE.replace("__SUBTITLE__", subtitle)
                .replace("__LOW__", str(LOW_CONFIDENCE))
                .replace("__DATA__", data))
    open(path, "w", encoding="utf-8").write(page)
    print(f"Wrote {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="clef", choices=["clef", "clef-flash"])
    parser.add_argument("--html-only", action="store_true", help="rebuild results.html from results.json")
    args = parser.parse_args()
    if args.html_only:
        output = json.load(open("results.json", encoding="utf-8"))
    else:
        output = run(args.model)
    write_html(output)


if __name__ == "__main__":
    main()
