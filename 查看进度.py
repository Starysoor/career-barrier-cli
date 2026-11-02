# -*- coding: utf-8 -*-
"""只读：回读当前账号各关真实完成状态（不写入任何数据）"""
import importlib.util

spec = importlib.util.spec_from_file_location("shua", "刷生涯闯关.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.load_config()

bt = m.browser_current_token()
m.TOKEN = bt or m.CFG.get("token", "")

info = m.fetch_account()
if not info:
    print("[!!] Token 无效或已过期，请先运行 刷生涯闯关.py 重新登录")
    raise SystemExit(1)

print("账号: %s %s | uid: %s" % (info.get("name"), m.mask_phone(info.get("mobile")), info.get("uid")))
print("账号来源:", "浏览器实时登录态" if bt else "缓存Token")
try:
    print("完赛标记 is_link_finish:", m.http_json("GET", m.API + "/barrier-ninths/all-barrier-finish-status", m.TOKEN))
except Exception as e:
    print("完赛标记读取失败:", e)
print()

rows = []
for idx, (sid, name, _) in enumerate(m.BARRIERS, 1):
    ok, detail = m.verify_barrier(idx)
    rows.append((name, ok, detail))
    print("  %s %d %-6s %s" % ("✅" if ok else "❌", idx, name, detail))

print()
print("真实完成 %d/8 关" % sum(1 for _, ok, _ in rows if ok))
