path = "/etc/caddy/Caddyfile"
with open(path, encoding="utf-8") as f:
    content = f.read()

old = '\t\theader @assets Cache-Control "public, max-age=31536000, immutable"'
new = '\t\theader @assets Cache-Control "no-cache"'

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("PATCHED: assets -> no-cache")
elif "no-cache" in content and "@assets" in content:
    print("ALREADY no-cache")
else:
    print("PATTERN NOT FOUND")
    idx = content.find("@assets")
    print(repr(content[idx-20:idx+120]))
