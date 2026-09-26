#!/usr/bin/env python3
"""Dependency-free, polished web interface for Mint Message Archive."""
import html
import mimetypes
import pathlib
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone

PAGE_SIZE = 40


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def params(handler):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)


def val(p, key, default=""):
    return p.get(key, [default])[0].strip()


def send_html(handler, text, status=200):
    data = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def layout(title, content, active="search"):
    search_active = "active" if active == "search" else ""
    about_active = "active" if active == "about" else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>{esc(title)} · Mint Message Archive</title><style>
:root{{--bg:#f4f6f8;--surface:#fff;--surface2:#f8fafc;--text:#172033;--muted:#667085;--line:#e4e7ec;--accent:#2563eb;--accent2:#1d4ed8;--shadow:0 12px 35px rgba(16,24,40,.08);--radius:16px}}@media(prefers-color-scheme:dark){{:root{{--bg:#0b1018;--surface:#111827;--surface2:#172033;--text:#edf2f7;--muted:#98a2b3;--line:#273244;--accent:#60a5fa;--accent2:#93c5fd;--shadow:0 16px 45px rgba(0,0,0,.3)}}}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}.top{{height:66px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;align-items:center;position:sticky;top:0;z-index:10}}.nav{{width:min(1180px,calc(100% - 32px));margin:auto;display:flex;align-items:center;gap:28px}}.brand{{font-weight:800;letter-spacing:-.03em;font-size:18px;display:flex;align-items:center;gap:10px;color:var(--text)}}.logo{{width:34px;height:34px;border-radius:10px;background:var(--accent);color:#fff;display:grid;place-items:center;font-weight:900}}.links{{display:flex;gap:6px;margin-left:auto}}.links a{{padding:8px 12px;border-radius:9px;color:var(--muted);font-weight:650}}.links a.active,.links a:hover{{background:var(--surface2);color:var(--text);text-decoration:none}}main{{width:min(1180px,calc(100% - 32px));margin:34px auto 60px}}.hero{{margin-bottom:24px}}.eyebrow{{color:var(--accent);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.09em}}h1{{font-size:32px;line-height:1.15;letter-spacing:-.04em;margin:6px 0 8px}}.sub,.meta{{color:var(--muted)}}.sub{{font-size:15px}}.card{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}}.search{{padding:20px;margin-bottom:20px}}.grid{{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:12px}}.field label{{display:block;font-size:12px;font-weight:750;color:var(--muted);margin-bottom:6px}}input,select{{width:100%;height:42px;border:1px solid var(--line);border-radius:10px;background:var(--surface2);color:var(--text);padding:0 12px;outline:0}}input:focus,select:focus{{border-color:var(--accent);box-shadow:0 0 0 3px rgba(37,99,235,.12)}}.actions{{display:flex;gap:10px;align-items:end;height:68px}}button,.button{{height:40px;border:0;border-radius:10px;padding:0 16px;background:var(--accent);color:#fff;font-weight:750;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;text-decoration:none}}button:hover,.button:hover{{background:var(--accent2);text-decoration:none}}.ghost{{background:var(--surface2);color:var(--text);border:1px solid var(--line)}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}.stat{{padding:17px 18px}}.stat .n{{font-size:24px;font-weight:850;letter-spacing:-.03em}}.stat .l{{font-size:12px;color:var(--muted);margin-top:2px}}.results-head{{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--line)}}.item{{padding:17px 20px;border-bottom:1px solid var(--line);display:flex;gap:15px;align-items:flex-start}}.item:last-child{{border-bottom:0}}.avatar{{width:40px;height:40px;border-radius:12px;background:var(--surface2);display:grid;place-items:center;font-weight:800;color:var(--accent);flex:0 0 auto}}.msg{{min-width:0;flex:1}}.row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}.who{{font-weight:750}}.date{{color:var(--muted);font-size:12px;margin-left:auto}}.preview{{display:block;color:var(--muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:900px}}.badges{{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}}.badge{{font-size:11px;font-weight:700;padding:3px 7px;border-radius:999px;background:var(--surface2);color:var(--muted)}}.empty{{padding:55px 20px;text-align:center;color:var(--muted)}}.empty strong{{display:block;color:var(--text);font-size:16px;margin-bottom:4px}}.pager{{display:flex;justify-content:space-between;align-items:center;padding:14px 20px}}.pager a{{padding:7px 11px;border:1px solid var(--line);border-radius:9px;background:var(--surface2)}}.detail{{padding:26px}}.detail-head{{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:20px}}.body{{font-size:16px;white-space:pre-wrap;word-break:break-word;background:var(--surface2);border-radius:12px;padding:18px}}.participants{{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 18px}}.part{{border:1px solid var(--line);padding:5px 9px;border-radius:999px;font-size:12px}}.attachments{{margin-top:22px}}.attachment-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-top:12px}}.att{{overflow:hidden;border:1px solid var(--line);border-radius:14px;background:var(--surface2)}}.att-preview{{aspect-ratio:4/3;background:#0b1018;display:grid;place-items:center;overflow:hidden}}.att-preview img,.att-preview video{{width:100%;height:100%;object-fit:contain}}.att-preview audio{{width:calc(100% - 20px)}}.att-icon{{font-size:34px;color:var(--muted)}}.att-info{{padding:11px 12px}}.att-name{{display:block;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.att-meta{{font-size:12px;color:var(--muted);margin-top:3px}}.att-actions{{display:flex;gap:8px;margin-top:9px}}.att-actions a{{font-size:12px;font-weight:700}}@media(max-width:800px){{.grid{{grid-template-columns:1fr 1fr}}.stats{{grid-template-columns:1fr 1fr}}.date{{width:100%;margin-left:0}}.actions{{height:auto;margin-top:4px}}}}@media(max-width:520px){{.grid,.stats{{grid-template-columns:1fr}}main{{margin-top:24px}}h1{{font-size:27px}}.links a:not(.active){{display:none}}}}
</style></head><body><header class="top"><nav class="nav"><a class="brand" href="/"><span class="logo">M</span>Mint Message Archive</a><div class="links"><a class="{search_active}" href="/">Search</a><a class="{about_active}" href="/about">About</a></div></nav></header><main>{content}</main></body></html>'''


def fmt_date(ts):
    if not ts: return "Unknown date"
    try: return datetime.fromtimestamp(int(ts)/1000,timezone.utc).astimezone().strftime("%b %-d, %Y · %-I:%M %p")
    except Exception: return str(ts)


def contact(row, parts):
    if row["message_type"] == "SMS": return row["address"] or "Unknown contact"
    for p in parts:
        if p["role"] == "FROM": return p["address"]
    return parts[0]["address"] if parts else "MMS message"


def search_page(handler):
    p=params(handler); q=val(p,"q"); device=val(p,"device"); kind=val(p,"type"); who=val(p,"contact"); df=val(p,"from"); dt=val(p,"to"); att=val(p,"attachment")
    try: page=max(1,int(val(p,"page","1")))
    except ValueError: page=1
    offset=(page-1)*PAGE_SIZE
    with handler.server.database.connect() as con:
        devices=con.execute("SELECT device_id,device_alias FROM devices ORDER BY COALESCE(NULLIF(device_alias,''),device_id)").fetchall()
        total=con.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"]
        where=["1=1"]; args=[]
        if q:
            like=f"%{q}%"; where.append("(m.body LIKE ? OR m.subject LIKE ? OR m.address LIKE ? OR EXISTS (SELECT 1 FROM message_participants p WHERE p.device_id=m.device_id AND p.message_type=m.message_type AND p.message_id=m.message_id AND p.address LIKE ?) OR EXISTS (SELECT 1 FROM mms_parts x WHERE x.device_id=m.device_id AND x.message_id=m.message_id AND x.text LIKE ?) OR EXISTS (SELECT 1 FROM attachments z WHERE z.device_id=m.device_id AND z.message_id=m.message_id AND z.filename LIKE ?))"); args += [like]*6
        if device: where.append("m.device_id=?"); args.append(device)
        if kind in ("SMS","MMS","RCS"): where.append("m.message_type=?"); args.append(kind)
        if who:
            like=f"%{who}%"; where.append("(m.address LIKE ? OR EXISTS (SELECT 1 FROM message_participants p WHERE p.device_id=m.device_id AND p.message_type=m.message_type AND p.message_id=m.message_id AND p.address LIKE ?))"); args += [like,like]
        try:
            if df: where.append("m.timestamp>=?"); args.append(int(datetime.strptime(df,"%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000))
            if dt: where.append("m.timestamp<?"); args.append(int((datetime.strptime(dt,"%Y-%m-%d")+timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp()*1000))
        except ValueError: pass
        if att=="yes": where.append("EXISTS (SELECT 1 FROM attachments z WHERE z.device_id=m.device_id AND z.message_id=m.message_id)")
        if att=="no": where.append("NOT EXISTS (SELECT 1 FROM attachments z WHERE z.device_id=m.device_id AND z.message_id=m.message_id)")
        clause=" AND ".join(where); count=con.execute(f"SELECT COUNT(*) n FROM messages m WHERE {clause}",args).fetchone()["n"]
        rows=con.execute(f"SELECT m.*,d.device_alias FROM messages m JOIN devices d ON d.device_id=m.device_id WHERE {clause} ORDER BY m.timestamp DESC,m.id DESC LIMIT ? OFFSET ?",args+[PAGE_SIZE,offset]).fetchall()
        data=[]
        for row in rows:
            parts=con.execute("SELECT address,role FROM message_participants WHERE device_id=? AND message_type=? AND message_id=? ORDER BY CASE role WHEN 'FROM' THEN 0 WHEN 'TO' THEN 1 ELSE 2 END,address",(row["device_id"],row["message_type"],row["message_id"])).fetchall()
            n=con.execute("SELECT COUNT(*) n FROM attachments WHERE device_id=? AND message_id=?",(row["device_id"],row["message_id"])).fetchone()["n"]
            data.append((row,parts,n))
    opts=['<option value="">All phones</option>']
    for d in devices:
        sel=" selected" if d["device_id"]==device else ""; opts.append(f'<option value="{esc(d["device_id"])}"{sel}>{esc(d["device_alias"] or d["device_id"])}</option>')
    kinds=['<option value="">All types</option>']
    for t in ("SMS","MMS","RCS"):
        sel=" selected" if kind==t else ""; kinds.append(f'<option value="{t}"{sel}>{t}</option>')
    ao=['<option value="">Any</option>']
    for x,label in (("yes","With attachments"),("no","Without attachments")):
        sel=" selected" if att==x else ""; ao.append(f'<option value="{x}"{sel}>{label}</option>')
    items=[]
    for row,parts,n in data:
        href="/message?"+urllib.parse.urlencode({"device":row["device_id"],"type":row["message_type"],"id":row["message_id"]}); body=row["body"] or row["subject"] or "(No message text)"
        badges=[f'<span class="badge">{esc(row["message_type"])}</span>']
        if row["device_alias"]: badges.append(f'<span class="badge">{esc(row["device_alias"])}</span>')
        if n: badges.append(f'<span class="badge">📎 {n}</span>')
        items.append(f'<article class="item"><div class="avatar">{esc((row["message_type"] or "?")[0])}</div><div class="msg"><div class="row"><a class="who" href="{href}">{esc(contact(row,parts))}</a><span class="date">{esc(fmt_date(row["timestamp"]))}</span></div><a href="{href}" class="preview">{esc(body)}</a><div class="badges">{"".join(badges)}</div></div></article>')
    results="".join(items) if items else '<div class="empty"><strong>No messages found</strong>Try broadening your search or clearing a filter.</div>'
    pages=max(1,(count+PAGE_SIZE-1)//PAGE_SIZE); base={k:v[0] for k,v in p.items() if k!="page" and v and v[0]}
    prev="#" if page<=1 else "/?"+urllib.parse.urlencode({**base,"page":page-1}); nxt="#" if page>=pages else "/?"+urllib.parse.urlencode({**base,"page":page+1})
    start=offset+1 if count else 0; end=min(offset+len(data),count)
    content=f'''<section class="hero"><div class="eyebrow">Private message archive</div><h1>Search your messages</h1><div class="sub">Fast, local search across every phone and every archived message indexed on this server.</div></section><div class="stats"><div class="card stat"><div class="n">{total:,}</div><div class="l">Total messages</div></div><div class="card stat"><div class="n">{sum(1 for r,_,_ in data if r["message_type"]=="SMS"):,}</div><div class="l">SMS on this page</div></div><div class="card stat"><div class="n">{sum(1 for r,_,_ in data if r["message_type"]=="MMS"):,}</div><div class="l">MMS on this page</div></div><div class="card stat"><div class="n">{len(devices):,}</div><div class="l">Devices</div></div></div><form class="card search" method="get"><div class="grid"><div class="field"><label>Keyword, phone number, filename</label><input name="q" value="{esc(q)}" placeholder="Search message text…"></div><div class="field"><label>Phone</label><select name="device">{"".join(opts)}</select></div><div class="field"><label>Message type</label><select name="type">{"".join(kinds)}</select></div><div class="field"><label>Sender / recipient</label><input name="contact" value="{esc(who)}" placeholder="Name or number"></div></div><div class="grid" style="margin-top:12px"><div class="field"><label>From date</label><input type="date" name="from" value="{esc(df)}"></div><div class="field"><label>To date</label><input type="date" name="to" value="{esc(dt)}"></div><div class="field"><label>Attachments</label><select name="attachment">{"".join(ao)}</select></div><div class="actions"><button type="submit">Search archive</button><a class="button ghost" href="/">Clear</a></div></div></form><section class="card"><div class="results-head"><strong>{count:,} matching message{'s' if count!=1 else ''}</strong><span class="meta">Page {page:,} of {pages:,}</span></div>{results}<div class="pager"><a href="{prev}">← Previous</a><span class="meta">Showing {start:,}–{end:,}</span><a href="{nxt}">Next →</a></div></section>'''
    return layout("Search",content)


def message_page(handler):
    p=params(handler); device=val(p,"device"); kind=val(p,"type"); mid=val(p,"id")
    with handler.server.database.connect() as con:
        row=con.execute("SELECT m.*,d.device_alias FROM messages m JOIN devices d ON d.device_id=m.device_id WHERE m.device_id=? AND m.message_type=? AND m.message_id=?",(device,kind,mid)).fetchone()
        if not row: return layout("Not found",'<div class="card empty"><strong>Message not found</strong>The requested message is not in the archive.</div>'),404
        parts=con.execute("SELECT address,role FROM message_participants WHERE device_id=? AND message_type=? AND message_id=? ORDER BY address",(device,kind,mid)).fetchall()
        atts=con.execute("SELECT * FROM attachments WHERE device_id=? AND message_id=? ORDER BY id",(device,mid)).fetchall()
    participant_html="".join(f'<span class="part"><b>{esc(x["role"])}</b> {esc(x["address"])}</span>' for x in parts)
    participant_block=f'<div class="participants">{participant_html}</div>' if participant_html else ''
    attachment_html=[]
    for a in atts:
        href="/attachment?"+urllib.parse.urlencode({"device":device,"archive":a["archive_id"],"path":a["archive_path"]})
        mime=(a["mime_type"] or "").lower()
        if mime.startswith("image/"):
            preview=f'<img src="{href}" alt="{esc(a["filename"])}" loading="lazy">'
        elif mime.startswith("video/"):
            preview=f'<video controls preload="metadata"><source src="{href}" type="{esc(mime)}"></video>'
        elif mime.startswith("audio/"):
            preview=f'<audio controls preload="metadata"><source src="{href}" type="{esc(mime)}"></audio>'
        else:
            icon="📄"
            if mime=="application/pdf": icon="📕"
            elif mime.startswith("text/"): icon="📝"
            elif mime.startswith("application/zip") or mime.endswith("+zip"): icon="🗜️"
            preview=f'<div class="att-icon">{icon}</div>'
        attachment_html.append(
            f'<article class="att"><a class="att-preview" href="{href}" target="_blank" rel="noopener">{preview}</a>'
            f'<div class="att-info"><a class="att-name" href="{href}" target="_blank" rel="noopener">{esc(a["filename"])}</a>'
            f'<div class="att-meta">{esc(a["mime_type"] or "file")} · {(a["size"] or 0):,} bytes</div>'
            f'<div class="att-actions"><a href="{href}" target="_blank" rel="noopener">Open</a>'
            f'<a href="{href}&download=1">Download</a></div></div></article>'
        )
    attachments_block=f'<div class="attachment-grid">{"".join(attachment_html)}</div>' if attachment_html else '<div class="meta">No attachments</div>'
    back="/?"+urllib.parse.urlencode({"device":device})
    thread_href = "/thread?" + urllib.parse.urlencode({"device": device, "thread": row["thread_id"]}) if row["thread_id"] else ""
    thread_link = f'<a class="button ghost" href="{thread_href}">View conversation</a>' if thread_href else ""
    content=f'<div class="hero"><a href="{back}">← Back to search</a></div><section class="card detail"><div class="detail-head"><div><div class="eyebrow">{esc(row["message_type"])}</div><h1>{esc(contact(row,parts))}</h1><div class="meta">{esc(fmt_date(row["timestamp"]))} · {esc(row["device_alias"] or device)}</div></div><div class="row"><span class="badge">Thread {esc(row["thread_id"] or "—")}</span>{thread_link}</div></div>{participant_block}<div class="body">{esc(row["body"] or row["subject"] or "(No message text)")}</div><div class="attachments"><h3>Attachments</h3>{attachments_block}</div></section>'
    return layout("Message",content), 200


def thread_page(handler):
    p = params(handler)
    device = val(p, "device")
    thread_id = val(p, "thread")

    if not device or not thread_id:
        return layout(
            "Conversation not found",
            '<div class="card empty"><strong>Conversation not found</strong>A device and thread are required.</div>',
        ), 404

    with handler.server.database.connect() as con:
        rows = con.execute(
            """
            SELECT m.*, d.device_alias,
                   (
                       SELECT p.address
                       FROM message_participants p
                       WHERE p.device_id = m.device_id
                         AND p.message_type = m.message_type
                         AND p.message_id = m.message_id
                         AND p.role = 'FROM'
                       ORDER BY p.id
                       LIMIT 1
                   ) AS display_sender
            FROM messages m
            JOIN devices d ON d.device_id = m.device_id
            WHERE m.device_id = ? AND m.thread_id = ?
            ORDER BY m.timestamp ASC, m.id ASC
            """,
            (device, thread_id),
        ).fetchall()

        if not rows:
            return layout(
                "Conversation not found",
                '<div class="card empty"><strong>Conversation not found</strong>The requested conversation is not in the archive.</div>',
            ), 404

        participant_rows = con.execute(
            """
            SELECT message_id, address, role
            FROM message_participants
            WHERE device_id = ?
              AND message_type = 'MMS'
              AND message_id IN (
                  SELECT message_id FROM messages
                  WHERE device_id = ? AND thread_id = ?
              )
            ORDER BY message_id,
                     CASE role WHEN 'FROM' THEN 0 WHEN 'TO' THEN 1 ELSE 2 END,
                     address
            """,
            (device, device, thread_id),
        ).fetchall()

        participants = []
        participants_by_message = {}
        for participant in participant_rows:
            participants.append(participant)
            participants_by_message.setdefault(str(participant["message_id"]), []).append(participant)

        attachment_count = con.execute(
            """
            SELECT COUNT(*)
            FROM attachments a
            JOIN messages m
              ON m.device_id = a.device_id
             AND m.message_type = 'MMS'
             AND m.message_id = a.message_id
            WHERE m.device_id = ? AND m.thread_id = ?
            """,
            (device, thread_id),
        ).fetchone()[0]

    items = []
    for row in rows:
        detail_href = "/message?" + urllib.parse.urlencode({
            "device": device,
            "type": row["message_type"],
            "id": row["message_id"],
        })
        row_parts = participants_by_message.get(str(row["message_id"]), [])
        body = row["body"] or row["subject"] or "(No message text)"
        badge = esc(row["message_type"])
        if row["message_type"] == "MMS":
            sender = row["display_sender"] or "Unknown MMS sender"
        else:
            sender = row["address"] or "Unknown contact"
        items.append(
            f'<article class="item">'
            f'<div class="avatar">{esc((row["message_type"] or "?")[0])}</div>'
            f'<div class="msg">'
            f'<div class="row"><a class="who" href="{detail_href}">{esc(sender)}</a>'
            f'<span class="date">{esc(fmt_date(row["timestamp"]))}</span></div>'
            f'<div class="preview" style="white-space:pre-wrap">{esc(body)}</div>'
            f'<div class="badges"><span class="badge">{badge}</span>'
            f'</div></div></article>'
        )

    title_contact = next((x["address"] for x in participants if x["role"] == "FROM"), rows[0]["display_sender"] or (participants[0]["address"] if participants else contact(rows[0], [])))
    back = "/?" + urllib.parse.urlencode({"device": device})
    content = (
        f'<div class="hero"><a href="{back}">← Back to search</a></div>'
        f'<section class="card detail">'
        f'<div class="detail-head"><div><div class="eyebrow">Conversation</div>'
        f'<h1>{esc(title_contact)}</h1>'
        f'<div class="meta">{len(rows):,} messages · {esc(rows[0]["device_alias"] or device)}'
        f' · Thread {esc(thread_id)}</div></div>'
        f'<span class="badge">📎 {attachment_count:,} attachment'
        f'{"s" if attachment_count != 1 else ""}</span></div>'
        f'<div>{"".join(items)}</div>'
        f'</section>'
    )
    return layout("Conversation", content), 200



def about_page():
    content='<section class="hero"><div class="eyebrow">About</div><h1>Your messages. Your archive.</h1><div class="sub">A polished local interface for messages stored on your own Linux archive server.</div></section><section class="card detail"><h2>How it works</h2><p>Android phones create incremental ZIP archives. The Linux server preserves those original archives and indexes their contents in SQLite for fast searching.</p><div class="body">Android → Incremental ZIP → Linux Archive → SQLite Search Index → Web Interface</div><h2>Privacy</h2><p>Message content and attachments remain on the archive server. Keep the interface restricted to your trusted network and protect the archive directory and server account.</p><h2>Message types</h2><p><b>SMS</b> and <b>MMS</b> are indexed today. The database architecture also reserves <b>RCS</b> for future supported RCS ingestion.</p></section>'
    return layout("About",content,"about")


def handle_get(handler):
    path=urllib.parse.urlsplit(handler.path).path
    if path not in ("/","/about","/message","/thread","/attachment"): return False
    if not handler.authorized(): handler.send_json(401,{"error":"unauthorized"}); return True
    if path=="/": send_html(handler,search_page(handler)); return True
    if path=="/about": send_html(handler,about_page()); return True
    if path=="/message":
        body,status=message_page(handler); send_html(handler,body,status); return True
    if path=="/thread":
        body,status=thread_page(handler); send_html(handler,body,status); return True
    p=params(handler); device=val(p,"device"); archive_id=val(p,"archive"); member=val(p,"path"); download=val(p,"download")
    if not device or not archive_id or not member or not member.startswith("attachments/") or ".." in pathlib.PurePosixPath(member).parts:
        handler.send_json(400,{"error":"invalid attachment path"}); return True
    with handler.server.database.connect() as con:
        row=con.execute(
            "SELECT archive_path FROM archives WHERE id=? AND device_id=?",
            (archive_id,device),
        ).fetchone()
        attachment=con.execute(
            "SELECT mime_type, filename FROM attachments "
            "WHERE device_id=? AND archive_id=? AND archive_path=? "
            "LIMIT 1",
            (device,archive_id,member),
        ).fetchone()
    if not row: handler.send_json(404,{"error":"archive not found"}); return True
    try:
        with zipfile.ZipFile(row["archive_path"],"r") as z: data=z.read(member)
    except (KeyError,OSError,zipfile.BadZipFile): handler.send_json(404,{"error":"attachment not found"}); return True
    safe_name=pathlib.PurePath(member).name.replace('"',"")
    content_type=(attachment["mime_type"] if attachment and attachment["mime_type"] else None) or mimetypes.guess_type(member)[0] or "application/octet-stream"
    disposition="attachment" if download else "inline"
    handler.send_response(200); handler.send_header("Content-Type",content_type); handler.send_header("Content-Length",str(len(data))); handler.send_header("Content-Disposition",f'{disposition}; filename="{safe_name}"'); handler.end_headers(); handler.wfile.write(data); return True
