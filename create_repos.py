#!/usr/bin/env python3
"""
Shopilo GitHub Repos Creator, Multi-country support

Usage:
  python3 create_repos.py --token TOKEN --username shopilo-ro --country ro
  python3 create_repos.py --token TOKEN --username shopilo-de --country de
  python3 create_repos.py --token TOKEN --username shopilo-fr --country fr

Fiecare tara are un folder shopilo.{tld}/ cu:
  stores.py  - COUNTRY_CONFIG + STORES lista de magazine

Obtine tokenul din: GitHub -> Settings -> Developer settings -> Personal access tokens
Permisiuni necesare: repo (full control)
"""

import argparse
import base64
import importlib.util
import json
import os
import sys
import time
import calendar
import requests
from datetime import datetime

NOW      = datetime.now()
YEAR_STR = str(NOW.year)

# Expiry dinamic: intotdeauna NOW + 6 luni (regenerat lunar de GitHub Action)
def _six_months_from_now():
    month = NOW.month + 6
    year  = NOW.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day   = min(NOW.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day)

EXPIRY_DATE = _six_months_from_now().strftime("%Y-%m-%d")

# Setate dinamic in main() pe baza COUNTRY_CONFIG
SHOPILO_DOMAIN = "shopilo.ro"
STORE_PATH     = "magazin"
MONTH_STR      = ""
T              = {}  # translations dict, set in main() from config["t"]


# ─── GITHUB API ───────────────────────────────────────────────────────────────

class GitHubAPI:
    def __init__(self, token, username):
        self.token = token
        self.username = username
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        })

    def create_repo(self, name, description):
        r = self.session.post("https://api.github.com/user/repos", json={
            "name": name,
            "description": description,
            "private": False,
            "auto_init": False,
            "has_issues": False,
            "has_projects": False,
            "has_wiki": False
        })
        if r.status_code == 201:
            return True, "creat"
        elif r.status_code == 422:
            return True, "exista deja"
        else:
            return False, r.json().get("message", str(r.status_code))

    def create_file(self, repo, path, content, message):
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        r = self.session.put(
            f"https://api.github.com/repos/{self.username}/{repo}/contents/{path}",
            json={"message": message, "content": encoded}
        )
        return r.status_code in (200, 201)

    def enable_pages(self, repo):
        r = self.session.post(
            f"https://api.github.com/repos/{self.username}/{repo}/pages",
            json={"source": {"branch": "main", "path": "/"}}
        )
        return r.status_code in (200, 201)

    def update_file(self, repo, path, content, message):
        """Actualizeaza un fisier existent (necesita SHA-ul curent)."""
        r = self.session.get(
            f"https://api.github.com/repos/{self.username}/{repo}/contents/{path}"
        )
        if r.status_code != 200:
            return False
        sha = r.json().get("sha")
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        r = self.session.put(
            f"https://api.github.com/repos/{self.username}/{repo}/contents/{path}",
            json={"message": message, "content": encoded, "sha": sha}
        )
        return r.status_code in (200, 201)


# ─── GENERARE CONTINUT ────────────────────────────────────────────────────────

def make_readme(store_name, repo_slug, shopilo_slug, example_code,
                example_discount, example_desc, example_date, username):
    shopilo_url = f"https://{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}"
    pages_url   = f"https://{username}.github.io"
    store_lower = store_name.lower().replace(" ", "-").replace(".", "")
    fmtargs = dict(store=store_name, domain=SHOPILO_DOMAIN, url=shopilo_url,
                   slug=shopilo_slug, store_path=STORE_PATH)
    return f"""# {T["readme_title"].format(**fmtargs)}

{T["readme_intro"].format(**fmtargs)}

**{T["readme_live_page"]}** [{username}.github.io/{repo_slug}]({pages_url}/{repo_slug}/)

![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue) ![License MIT](https://img.shields.io/badge/license-MIT-green)

## {T["readme_h_install"]}

```bash
pip install requests beautifulsoup4
git clone https://github.com/{username}/{repo_slug}
cd {repo_slug}
python fetch.py
```

## {T["readme_h_output"]}

```json
[
  {{
    "store": "{store_name}",
    "code": "{example_code}",
    "discount": "{example_discount}",
    "description": "{example_desc}",
    "expires": "{EXPIRY_DATE}",
    "source": "{shopilo_url}"
  }}
]
```

## {T["readme_h_coupons"].format(**fmtargs)}

| {T["readme_th_discount"]} | {T["readme_th_description"]} | {T["readme_th_source"]} |
|----------|-----------|-------|
| {example_discount} | {example_desc} | [{SHOPILO_DOMAIN}]({shopilo_url}) |

{T["readme_active_codes"]} **[{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}]({shopilo_url})**

## {T["readme_h_faq"]}

### {T["readme_faq1_q"].format(**fmtargs)}
{T["readme_faq1_a"].format(**fmtargs)}

### {T["readme_faq2_q"].format(**fmtargs)}
{T["readme_faq2_a"].format(**fmtargs)}

### {T["readme_faq3_q"].format(**fmtargs)}
{T["readme_faq3_a"].format(**fmtargs)}

### {T["readme_faq4_q"].format(**fmtargs)}
{T["readme_faq4_a"].format(**fmtargs)}

## {T["readme_h_about"].format(**fmtargs)}

{T["readme_about_text"].format(**fmtargs)}

## {T["readme_h_npm"]}

```bash
npm install {repo_slug}
```

```javascript
const {{ fetchCoupons }} = require('{repo_slug}');
fetchCoupons().then(data => console.log(data));
```

## {T["readme_h_license"]}

{T["readme_license_text"].format(**fmtargs)}
"""


def make_fetch_py(store_name, repo_slug, shopilo_slug, username):
    shopilo_url = f"https://{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}"
    fmtargs = dict(store=store_name, domain=SHOPILO_DOMAIN, store_name=store_name)
    t_docstring  = T["fetch_docstring"].format(**fmtargs)
    t_returns    = T["fetch_returns"].format(**fmtargs)
    t_error      = T["fetch_error"]
    # For the running message, replace {store_name} with the runtime variable reference
    t_running    = T["fetch_running"].format(domain=SHOPILO_DOMAIN, store_name="{{STORE_NAME}}")
    # For the generated .py, we need runtime f-string expressions.
    # Split templates around {count} placeholder for the total line.
    t_total      = T["fetch_total"].replace("{count}", "{{len(coupons)}}")
    t_none       = T["fetch_none"]
    return f"""#!/usr/bin/env python3
\"\"\"
{t_docstring}
Sursa: {shopilo_url}
\"\"\"

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

SHOPILO_URL = "{shopilo_url}"
STORE_NAME = "{store_name}"


def fetch_coupons(url=SHOPILO_URL):
    \"\"\"{t_returns}\"\"\"
    headers = {{
        "User-Agent": "Mozilla/5.0 (compatible; coupon-fetcher/1.0; +https://github.com/{username}/{repo_slug})"
    }}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"{t_error} {{e}}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    coupons = []

    for item in soup.select(".coupon-item, [data-coupon], .offer-card"):
        code_el     = item.select_one("[data-code], .coupon-code, .code")
        discount_el = item.select_one(".discount, .percent, .amount")
        desc_el     = item.select_one(".title, .description, h3")
        expires_el  = item.select_one(".expires, .expiry, [data-expires]")

        coupon = {{
            "store":      STORE_NAME,
            "code":       code_el.get_text(strip=True)     if code_el     else None,
            "discount":   discount_el.get_text(strip=True) if discount_el else None,
            "description":desc_el.get_text(strip=True)     if desc_el     else None,
            "expires":    expires_el.get_text(strip=True)  if expires_el  else None,
            "source":     SHOPILO_URL,
            "fetched_at": datetime.now().isoformat()
        }}

        if coupon["description"]:
            coupons.append(coupon)

    return coupons


if __name__ == "__main__":
    print(f"{t_running}\\n")
    coupons = fetch_coupons()

    if coupons:
        print(json.dumps(coupons, ensure_ascii=False, indent=2))
        print(f"\\n{t_total}")
    else:
        print(f"{t_none} {{SHOPILO_URL}}")
"""


def make_workflow_yml(username, country):
    return f"""name: Update Store Pages

on:
  schedule:
    - cron: '0 6 1 * *'   {T["wf_cron_comment"]}
  workflow_dispatch:       {T["wf_dispatch_comment"]}

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: {T["wf_step_deps"]}
        run: pip install requests

      - name: {T["wf_step_update"]}
        run: python3 create_repos.py --token "$GH_PAT" --username "{username}" --country "{country}" --update-html
        env:
          GH_PAT: ${{{{ secrets.GH_PAT }}}}
"""


def make_package_json(store_name, repo_slug, shopilo_slug, username):
    store_lower = store_name.lower().replace(" ", "-").replace(".", "")
    fmtargs = dict(store=store_name, domain=SHOPILO_DOMAIN, slug=store_lower)
    return json.dumps({
        "name": repo_slug,
        "version": "1.0.0",
        "description": T["pkg_desc"].format(**fmtargs),
        "main": "index.js",
        "keywords": [
            T["pkg_kw_prefix"],
            f"{T['pkg_kw_prefix']}-{store_lower}",
            T["pkg_kw_voucher"].format(**fmtargs),
            T["pkg_kw_coupon"].format(**fmtargs),
            T["pkg_kw_deals"],
            "shopilo",
            T["pkg_kw_coupons"]
        ],
        "author": username,
        "license": "MIT",
        "homepage": f"https://{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}",
        "repository": {
            "type": "git",
            "url": f"https://github.com/{username}/{repo_slug}.git"
        }
    }, indent=2, ensure_ascii=False)


def make_requirements():
    return "requests>=2.28.0\nbeautifulsoup4>=4.11.0\n"


def make_index_js(store_name, repo_slug, shopilo_slug, username):
    shopilo_url = f"https://{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}"
    fmtargs = dict(store=store_name, domain=SHOPILO_DOMAIN)
    t_docstring = T["js_docstring"].format(**fmtargs)
    t_total     = T["js_total"]
    t_none      = T["js_none"]
    t_error     = T["js_error"]
    return f"""#!/usr/bin/env node
/**
 * {t_docstring}
 * Homepage: {shopilo_url}
 */

const SHOPILO_URL = "{shopilo_url}";
const STORE_NAME  = "{store_name}";

async function fetchCoupons(url = SHOPILO_URL) {{
  const res = await fetch(url, {{
    headers: {{ "User-Agent": "coupon-fetcher/1.0 (+https://github.com/{username}/{repo_slug})" }}
  }});
  if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
  const html = await res.text();
  const codes = [...html.matchAll(/data-code=["']([^"']+)["']/gi)].map(m => m[1]);
  return codes.map(code => ({{ store: STORE_NAME, code, source: SHOPILO_URL }}));
}}

module.exports = {{ fetchCoupons, SHOPILO_URL, STORE_NAME }};

if (require.main === module) {{
  fetchCoupons()
    .then(data => {{
      if (data.length) {{
        console.log(JSON.stringify(data, null, 2));
        console.log(`\\nTotal: ${{data.length}} {t_total}`);
      }} else {{
        console.log(`{t_none} ${{SHOPILO_URL}}`);
      }}
    }})
    .catch(err => console.error("{t_error}", err.message));
}}
"""


def make_index_html(store_name, repo_slug, shopilo_slug, example_code,
                    example_discount, example_desc, example_date, username):
    shopilo_url = f"https://{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}"
    pages_url   = f"https://{username}.github.io"
    fmtargs = dict(store=store_name, domain=SHOPILO_DOMAIN, url=shopilo_url,
                   slug=shopilo_slug, store_path=STORE_PATH, repo=repo_slug,
                   month=MONTH_STR, year=YEAR_STR)
    faq_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": T["page_faq1_q"].format(**fmtargs),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": T["page_faq1_a"].format(**fmtargs)
                }
            },
            {
                "@type": "Question",
                "name": T["page_faq2_q"].format(**fmtargs),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": T["page_faq2_a"].format(**fmtargs)
                }
            },
            {
                "@type": "Question",
                "name": T["page_faq3_q"].format(**fmtargs),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": T["page_faq3_a"].format(**fmtargs)
                }
            },
            {
                "@type": "Question",
                "name": T["page_faq4_q"].format(**fmtargs),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": T["page_faq4_a"].format(**fmtargs)
                }
            },
            {
                "@type": "Question",
                "name": T["page_faq5_q"].format(**fmtargs),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": T["page_faq5_a"].format(**fmtargs)
                }
            }
        ]
    }, ensure_ascii=False, indent=2)
    breadcrumb_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": T["page_breadcrumb_home"], "item": pages_url},
            {"@type": "ListItem", "position": 2, "name": T["page_breadcrumb_store"].format(**fmtargs), "item": f"{pages_url}/{repo_slug}/"}
        ]
    }, ensure_ascii=False)
    webpage_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": T["page_webpage_name"].format(**fmtargs),
        "description": T["page_webpage_desc"].format(**fmtargs),
        "url": f"{pages_url}/{repo_slug}/",
        "dateModified": f"{YEAR_STR}-{NOW.month:02d}-01",
        "isPartOf": {"@type": "WebSite", "name": "Shopilo Dev", "url": pages_url},
        "about": {"@type": "Thing", "name": store_name}
    }, ensure_ascii=False)
    t_lang         = T.get("page_lang", "ro")
    t_title        = T["page_title"].format(**fmtargs)
    t_meta_desc    = T["page_meta_desc"].format(**fmtargs)
    t_og_title     = T["page_og_title"].format(**fmtargs)
    t_og_desc      = T["page_og_desc"].format(**fmtargs)
    t_nav_all      = T["page_nav_all"]
    t_hero_desc    = T["page_hero_desc"].format(**fmtargs)
    t_cta          = T["page_cta"].format(**fmtargs)
    t_h_install    = T["page_h_install"]
    t_install_deps = T["page_code_install_deps"]
    t_clone        = T["page_code_clone"]
    t_run          = T["page_code_run"]
    t_npm_alt      = T["page_code_npm_alt"]
    t_use_node     = T["page_code_use_node"]
    t_h_output     = T["page_h_output"]
    t_th_disc      = T["page_th_discount"]
    t_th_desc      = T["page_th_description"]
    t_th_src       = T["page_th_source"]
    t_active       = T["page_active_codes"]
    t_h_how        = T["page_h_how"]
    t_how1         = T["page_how_step1"].format(**fmtargs)
    t_how2         = T["page_how_step2"].format(**fmtargs)
    t_how3         = T["page_how_step3"].format(**fmtargs)
    t_how4         = T["page_how_step4"].format(**fmtargs)
    t_h_faq        = T["page_h_faq"].format(**fmtargs)
    t_pfaq1_q      = T["page_pfaq1_q"].format(**fmtargs)
    t_pfaq1_a      = T["page_pfaq1_a"].format(**fmtargs)
    t_pfaq2_q      = T["page_pfaq2_q"].format(**fmtargs)
    t_pfaq2_a      = T["page_pfaq2_a"].format(**fmtargs)
    t_pfaq3_q      = T["page_pfaq3_q"].format(**fmtargs)
    t_pfaq3_a      = T["page_pfaq3_a"].format(**fmtargs)
    t_pfaq4_q      = T["page_pfaq4_q"].format(**fmtargs)
    t_pfaq4_a      = T["page_pfaq4_a"].format(**fmtargs)
    t_pfaq5_q      = T["page_pfaq5_q"].format(**fmtargs)
    t_pfaq5_a      = T["page_pfaq5_a"].format(**fmtargs)
    t_sb_about     = T["page_sidebar_about"].format(**fmtargs)
    t_sb_about_txt = T["page_sidebar_about_txt"].format(**fmtargs)
    t_sb_howto     = T["page_sidebar_howto"].format(**fmtargs)
    t_howto1       = T["page_howto_step1"]
    t_howto2       = T["page_howto_step2"].format(**fmtargs)
    t_howto3       = T["page_howto_step3"]
    t_howto4       = T["page_howto_step4"]
    t_sb_kw        = T["page_sidebar_kw"]
    t_kw1          = T["page_kw1"].format(**fmtargs)
    t_kw2          = T["page_kw2"].format(**fmtargs)
    t_kw3          = T["page_kw3"].format(**fmtargs)
    t_kw4          = T["page_kw4"].format(**fmtargs)
    t_kw5          = T["page_kw5"].format(**fmtargs)
    t_kw6          = T["page_kw6"].format(**fmtargs)
    t_footer       = T["page_footer"]
    return f"""<!DOCTYPE html>
<html lang="{t_lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{t_title}</title>
  <meta name="description" content="{t_meta_desc}">
  <meta name="robots" content="index, follow">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{t_og_title}">
  <meta property="og:description" content="{t_og_desc}">
  <meta property="og:url" content="{pages_url}/{repo_slug}/">
  <script type="application/ld+json">{faq_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  <script type="application/ld+json">{webpage_schema}</script>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f6f8fa;color:#212529;line-height:1.6}}
    a{{color:#0969da;text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .wrap{{max-width:860px;margin:0 auto;padding:0 24px}}
    header{{background:#24292f;padding:14px 0}}
    .header-inner{{display:flex;justify-content:space-between;align-items:center}}
    .logo{{font-weight:600;color:#fff;font-size:15px}}
    nav a{{font-size:13px;color:#8b949e;margin-left:20px}}
    nav a:hover{{color:#fff;text-decoration:none}}
    .hero{{background:#fff;border-bottom:1px solid #e1e4e8;padding:40px 0 32px}}
    .breadcrumb{{font-size:13px;color:#57606a;margin-bottom:16px}}
    .breadcrumb a{{color:#57606a}}
    .repo-title{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
    .repo-icon{{color:#57606a;font-size:18px}}
    .hero h1{{font-size:22px;font-weight:600;color:#24292f;margin:0}}
    .hero h1 a{{color:#0969da}}
    .hero-desc{{color:#57606a;font-size:15px;margin:10px 0 20px;max-width:600px}}
    .badges{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}}
    .badge{{display:inline-flex;align-items:center;gap:4px;background:#f6f8fa;border:1px solid #e1e4e8;border-radius:4px;padding:3px 10px;font-size:12px;color:#57606a}}
    .badge-blue{{background:#ddf4ff;border-color:#54aeff;color:#0550ae}}
    .badge-green{{background:#dafbe1;border-color:#56d364;color:#1a7f37}}
    .cta{{display:inline-flex;align-items:center;gap:6px;background:#2da44e;color:#fff;padding:8px 18px;border-radius:6px;font-size:14px;font-weight:600;transition:.15s}}
    .cta:hover{{background:#2c974b;text-decoration:none}}
    main{{padding:32px 0 60px;display:grid;grid-template-columns:1fr 300px;gap:24px;align-items:start}}
    @media(max-width:700px){{main{{grid-template-columns:1fr}}}}
    .main-col{{display:flex;flex-direction:column;gap:20px}}
    .sidebar{{display:flex;flex-direction:column;gap:16px}}
    .card{{background:#fff;border:1px solid #e1e4e8;border-radius:10px;padding:20px}}
    .card h2{{font-size:15px;font-weight:600;margin-bottom:14px;color:#24292f;padding-bottom:10px;border-bottom:1px solid #e1e4e8}}
    .card h3{{font-size:14px;font-weight:600;color:#24292f;margin:0 0 4px}}
    pre{{background:#f6f8fa;border:1px solid #e1e4e8;border-radius:6px;padding:14px;font-size:13px;overflow-x:auto;line-height:1.5}}
    code{{font-family:'SFMono-Regular',Consolas,monospace;font-size:13px}}
    .inline-code{{background:#f6f8fa;border:1px solid #e1e4e8;border-radius:4px;padding:1px 6px;font-family:monospace;font-size:12px;color:#24292f}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th{{text-align:left;padding:8px 12px;background:#f6f8fa;border:1px solid #e1e4e8;font-weight:600;color:#57606a;font-size:12px}}
    td{{padding:8px 12px;border:1px solid #e1e4e8;color:#24292f}}
    td.mono{{font-family:monospace;font-weight:700;color:#0969da}}
    .tag-green{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;background:#dafbe1;color:#1a7f37}}
    .faq-item{{margin-bottom:16px}}
    .faq-item:last-child{{margin-bottom:0}}
    .faq-item h3{{font-size:14px;font-weight:600;color:#24292f;margin-bottom:4px}}
    .faq-item p{{font-size:13px;color:#57606a;line-height:1.6}}
    .kw-list{{display:flex;flex-wrap:wrap;gap:6px}}
    .kw{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;color:#0969da;border:1px solid #c8e1ff;background:#f1f8ff}}
    .kw:hover{{background:#ddf4ff;text-decoration:none}}
    .about-text{{font-size:13px;color:#57606a;line-height:1.7}}
    .steps{{display:flex;flex-direction:column;gap:10px;counter-reset:steps}}
    .step{{display:flex;gap:12px;align-items:flex-start;font-size:13px;color:#57606a}}
    .step-num{{background:#0969da;color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px}}
    footer{{background:#f6f8fa;border-top:1px solid #e1e4e8;padding:20px 0;font-size:12px;color:#57606a;text-align:center}}
  </style>
</head>
<body>

<header>
  <div class="wrap">
    <div class="header-inner">
      <a href="{pages_url}" class="logo">&#9679; {username}</a>
      <nav>
        <a href="{pages_url}">{t_nav_all}</a>
        <a href="https://github.com/{username}/{repo_slug}">GitHub</a>
        <a href="https://{SHOPILO_DOMAIN}">{SHOPILO_DOMAIN}</a>
      </nav>
    </div>
  </div>
</header>

<div class="hero">
  <div class="wrap">
    <div class="breadcrumb">
      <a href="https://github.com/{username}">{username}</a> /
      <a href="https://github.com/{username}/{repo_slug}">{repo_slug}</a>
    </div>
    <div class="repo-title">
      <span class="repo-icon">&#128196;</span>
      <h1><a href="{pages_url}">{username}</a> / {repo_slug}</h1>
    </div>
    <p class="hero-desc">{t_hero_desc}</p>
    <div class="badges">
      <span class="badge badge-blue">Python 3.8+</span>
      <span class="badge badge-green">MIT License</span>
      <span class="badge">requests + beautifulsoup4</span>
      <span class="badge">{SHOPILO_DOMAIN}</span>
    </div>
    <a href="{shopilo_url}" class="cta">
      &#128279; {t_cta}
    </a>
  </div>
</div>

<div class="wrap">
<main>
  <div class="main-col">

    <div class="card">
      <h2>{t_h_install}</h2>
      <pre><code>{t_install_deps}
pip install requests beautifulsoup4

{t_clone}
git clone https://github.com/{username}/{repo_slug}
cd {repo_slug}

{t_run}
python fetch.py</code></pre>
      <p style="font-size:13px;color:#57606a;margin-top:12px">{t_npm_alt}</p>
      <pre><code>npm install {repo_slug}

{t_use_node}
const {{ fetchCoupons }} = require('{repo_slug}');
fetchCoupons().then(data => console.log(data));</code></pre>
    </div>

    <div class="card">
      <h2>{t_h_output}, {MONTH_STR} {YEAR_STR}</h2>
      <pre><code>[
  {{
    "store": "{store_name}",
    "code": "{example_code}",
    "discount": "{example_discount}",
    "description": "{example_desc}",
    "expires": "{EXPIRY_DATE}",
    "source": "{shopilo_url}",
    "fetched_at": "{YEAR_STR}-{NOW.month:02d}-01T09:12:33"
  }}
]</code></pre>
      <table style="margin-top:14px">
        <thead>
          <tr>
            <th>{t_th_disc}</th><th>{t_th_desc}</th><th>{t_th_src}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{example_discount}</td>
            <td>{example_desc}</td>
            <td><a href="{shopilo_url}">{SHOPILO_DOMAIN}</a></td>
          </tr>
        </tbody>
      </table>
      <p style="font-size:12px;color:#57606a;margin-top:12px">
        {t_active}
        <a href="{shopilo_url}" style="font-weight:600">{SHOPILO_DOMAIN}/{STORE_PATH}/{shopilo_slug}</a>
      </p>
    </div>

    <div class="card">
      <h2>{t_h_how}</h2>
      <div class="steps">
        <div class="step"><span class="step-num">1</span><span>{t_how1}</span></div>
        <div class="step"><span class="step-num">2</span><span>{t_how2}</span></div>
        <div class="step"><span class="step-num">3</span><span>{t_how3}</span></div>
        <div class="step"><span class="step-num">4</span><span>{t_how4}</span></div>
      </div>
    </div>

    <div class="card">
      <h2>{t_h_faq}</h2>
      <div class="faq-item">
        <h3>{t_pfaq1_q}</h3>
        <p>{t_pfaq1_a}</p>
      </div>
      <div class="faq-item">
        <h3>{t_pfaq2_q}</h3>
        <p>{t_pfaq2_a}</p>
      </div>
      <div class="faq-item">
        <h3>{t_pfaq3_q}</h3>
        <p>{t_pfaq3_a}</p>
      </div>
      <div class="faq-item">
        <h3>{t_pfaq4_q}</h3>
        <p>{t_pfaq4_a}</p>
      </div>
      <div class="faq-item">
        <h3>{t_pfaq5_q}</h3>
        <p>{t_pfaq5_a}</p>
      </div>
    </div>

  </div>

  <div class="sidebar">

    <div class="card">
      <h2>{t_sb_about}</h2>
      <p class="about-text">{t_sb_about_txt}</p>
    </div>

    <div class="card">
      <h2>{t_sb_howto}</h2>
      <div class="steps">
        <div class="step"><span class="step-num">1</span><span>{t_howto1}</span></div>
        <div class="step"><span class="step-num">2</span><span>{t_howto2}</span></div>
        <div class="step"><span class="step-num">3</span><span>{t_howto3}</span></div>
        <div class="step"><span class="step-num">4</span><span>{t_howto4}</span></div>
      </div>
    </div>

    <div class="card">
      <h2>{t_sb_kw}</h2>
      <div class="kw-list">
        <a href="{shopilo_url}" class="kw">{t_kw1}</a>
        <a href="{shopilo_url}" class="kw">{t_kw2}</a>
        <a href="{shopilo_url}" class="kw">{t_kw3}</a>
        <a href="{shopilo_url}" class="kw">{t_kw4}</a>
        <a href="{shopilo_url}" class="kw">{t_kw5}</a>
        <a href="{shopilo_url}" class="kw">{t_kw6}</a>
      </div>
    </div>

  </div>
</main>
</div>

<footer>
  {t_footer} <a href="{shopilo_url}">{SHOPILO_DOMAIN}</a> |
  <a href="{pages_url}">{t_nav_all}</a>
</footer>

</body>
</html>
"""


def make_org_profile_readme(stores, username, config):
    """Genereaza profile/README.md pentru repo-ul .github (apare pe github.com/username)."""
    domain     = config["domain"]
    store_path = config.get("store_path", "magazin")
    pages_url  = f"https://{username}.github.io"
    n          = len(stores)
    prefix     = username.split("-")[0]
    fmtargs    = dict(domain=domain, n=n, prefix=prefix, month=MONTH_STR, year=YEAR_STR)

    rows = ""
    for i, (name, slug, shopilo_slug, code, disc, desc, date) in enumerate(stores, 1):
        shopilo_url = f"https://{domain}/{store_path}/{shopilo_slug}"
        rows += f"| {i} | [{name}](https://github.com/{username}/{slug}) | [{slug}](https://github.com/{username}/{slug}) | [{domain}/{store_path}/{shopilo_slug}]({shopilo_url}) |\n"

    t_desc      = T["org_profile_desc"].format(**fmtargs)
    t_main      = T["org_profile_main"]
    t_contains  = T["org_profile_contains"]
    t_b1        = T["org_profile_bullet1"]
    t_b2        = T["org_profile_bullet2"]
    t_b3        = T["org_profile_bullet3"].format(**fmtargs)
    t_b4        = T["org_profile_bullet4"]
    t_h_stores  = T["org_profile_h_stores"].format(**fmtargs)
    t_th_nr     = T["org_profile_th_nr"]
    t_th_store  = T["org_profile_th_store"]
    t_th_repo   = T["org_profile_th_repo"]
    t_th_live   = T["org_profile_th_live"]
    t_footer    = T["org_profile_footer"].format(**fmtargs)

    return f"""# {username}

{t_desc}

**{t_main}** [{pages_url}]({pages_url})

{t_contains}
- {t_b1}
- {t_b2}
- {t_b3}
- {t_b4}

---

## {t_h_stores}

| {t_th_nr} | {t_th_store} | {t_th_repo} | {t_th_live} |
|---|---------|------|-----------|
{rows}
---

{t_footer}
"""


def make_org_index_html(stores, username, config):
    """Genereaza pagina dark-theme pentru username.github.io din datele stores."""
    domain     = config["domain"]
    store_path = config.get("store_path", "magazin")
    hero_h1    = config.get("hero_h1",    f"Coduri de reducere - {domain}")
    hero_desc  = config.get("hero_desc",  f"Scripturi Python open-source pentru coduri de reducere de pe {domain}.")
    btn_prefix = config.get("btn_shop_prefix", "Cod reducere")
    n_stores   = len(stores)
    lang       = config.get("lang", "ro")
    fmtargs    = dict(domain=domain, username=username)

    t_badge_npm  = T.get("org_badge_npm",  "npm disponibil")
    t_badge_live = T.get("org_badge_live",  f"Date live {domain}").format(**fmtargs)
    t_code_inst  = T.get("org_code_install", "# Instaleaza dependentele")
    t_code_fetch = T.get("org_code_fetch",   "# Fetch automat coduri de reducere")
    t_clone_tpl  = T.get("org_code_clone_tpl", f"git clone https://github.com/{username}/cod-reducere-[magazin]").format(**fmtargs)
    t_stat_stores = T.get("org_stat_stores", "magazine")
    t_stat_source = T.get("org_stat_source", "Sursa date:")
    t_stat_lic    = T.get("org_stat_license", "Licenta:")
    t_stat_npm    = T.get("org_stat_npm_tpl", "cod-reducere-[magazin]")
    t_sec_title   = T.get("org_sec_title",   "Magazine")
    t_footer      = T.get("org_footer",      "Script open-source, Date de pe")

    OCTOCAT = '<svg height="13" width="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'
    GH_LOGO   = '<svg height="24" viewBox="0 0 16 16" width="24" fill="#e6edf3"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'

    cards_html = ""
    for name, slug, shopilo_slug, code, disc, desc, date in stores:
        shopilo_url = f"https://{domain}/{store_path}/{shopilo_slug}"
        cards_html += f"""
    <div class="card">
      <div class="card-head">
        <div class="card-name">{name}</div>
        <div class="card-slug">{slug}</div>
      </div>
      <div class="npm-box"><span class="npm-prompt">$</span>npm i {slug}</div>
      <div class="card-btns">
        <a href="https://github.com/{username}/{slug}" class="btn btn-gh" target="_blank" rel="noopener">
          {OCTOCAT}GitHub
        </a>
        <a href="{shopilo_url}" class="btn btn-shop" target="_blank" rel="noopener">{btn_prefix} {name}</a>
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{username} | {hero_h1}</title>
  <meta name="description" content="{hero_desc}">
  <meta name="robots" content="index, follow">
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:#0d1117;color:#e6edf3;line-height:1.5}}
    a{{color:#58a6ff;text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .wrap{{max-width:1200px;margin:0 auto;padding:0 24px}}
    header{{background:#161b22;border-bottom:1px solid #30363d;padding:14px 0}}
    .hdr{{display:flex;justify-content:space-between;align-items:center}}
    .logo{{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15px;color:#e6edf3;text-decoration:none}}
    nav a{{font-size:13px;color:#8b949e;margin-left:20px}}
    nav a:hover{{color:#e6edf3;text-decoration:none}}
    .hero{{padding:56px 0 40px}}
    .hero-eyebrow{{font-size:12px;color:#8b949e;font-family:'SFMono-Regular',Consolas,monospace;margin-bottom:12px}}
    .hero h1{{font-size:36px;font-weight:700;margin-bottom:16px;line-height:1.2}}
    .hero-desc{{font-size:16px;color:#8b949e;max-width:620px;margin-bottom:24px}}
    .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:28px}}
    .badge{{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:500;border:1px solid}}
    .badge-blue{{background:rgba(31,111,235,.1);border-color:#1f6feb;color:#79c0ff}}
    .badge-green{{background:rgba(35,134,54,.1);border-color:#238636;color:#56d364}}
    .badge-gray{{background:#21262d;border-color:#30363d;color:#8b949e}}
    .code-block{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px 24px;font-family:'SFMono-Regular',Consolas,monospace;font-size:13px;line-height:1.8;max-width:560px}}
    .c-comment{{color:#8b949e}}
    .c-cmd{{color:#e6edf3}}
    .stats{{background:#161b22;border-top:1px solid #30363d;border-bottom:1px solid #30363d;padding:14px 0;font-size:13px;color:#8b949e}}
    .stats-inner{{display:flex;flex-wrap:wrap;gap:24px}}
    .stat{{display:flex;align-items:center;gap:6px}}
    .stat-val{{color:#e6edf3;font-weight:600}}
    section{{padding:40px 0 60px}}
    .sec-hdr{{display:flex;align-items:center;gap:12px;margin-bottom:24px}}
    .sec-title{{font-size:18px;font-weight:600}}
    .sec-count{{background:#21262d;border:1px solid #30363d;border-radius:20px;padding:2px 10px;font-size:12px;color:#8b949e}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}}
    .card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;transition:.15s}}
    .card:hover{{border-color:#388bfd;box-shadow:0 0 0 3px rgba(56,139,253,.1)}}
    .card-head{{margin-bottom:12px}}
    .card-name{{font-size:15px;font-weight:600;color:#e6edf3;margin-bottom:2px}}
    .card-slug{{font-size:11px;color:#8b949e;font-family:'SFMono-Regular',Consolas,monospace}}
    .npm-box{{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:7px 11px;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px;color:#e6edf3;margin-bottom:12px}}
    .npm-prompt{{color:#3fb950;margin-right:6px;user-select:none}}
    .card-btns{{display:flex;gap:8px}}
    .btn{{display:inline-flex;align-items:center;gap:5px;padding:6px 14px;border-radius:6px;font-size:12px;font-weight:500;cursor:pointer;transition:.15s;white-space:nowrap}}
    .btn-gh{{background:#238636;color:#fff;border:1px solid rgba(240,246,252,.1)}}
    .btn-gh:hover{{background:#2ea043;text-decoration:none}}
    .btn-shop{{background:transparent;color:#e6edf3;border:1px solid #30363d}}
    .btn-shop:hover{{background:#21262d;text-decoration:none;border-color:#8b949e}}
    footer{{background:#161b22;border-top:1px solid #30363d;padding:20px 0;font-size:12px;color:#8b949e;text-align:center}}
    @media(max-width:600px){{.hero h1{{font-size:26px}}.stats-inner{{gap:14px}}}}
  </style>
</head>
<body>

<header>
  <div class="wrap">
    <div class="hdr">
      <a href="/" class="logo">{GH_LOGO}{username}</a>
      <nav>
        <a href="https://github.com/{username}" target="_blank" rel="noopener">GitHub</a>
        <a href="https://{domain}" target="_blank" rel="noopener">{domain}</a>
      </nav>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="hero">
    <div class="hero-eyebrow">github.com / {username}</div>
    <h1>{hero_h1}</h1>
    <p class="hero-desc">{hero_desc}</p>
    <div class="badges">
      <span class="badge badge-blue">Python 3.8+</span>
      <span class="badge badge-green">MIT License</span>
      <span class="badge badge-gray">{t_badge_npm}</span>
      <span class="badge badge-gray">{t_badge_live}</span>
    </div>
    <div class="code-block">
      <span class="c-comment">{t_code_inst}</span><br>
      <span class="c-cmd">pip install requests beautifulsoup4</span><br><br>
      <span class="c-comment">{t_code_fetch}</span><br>
      <span class="c-cmd">{t_clone_tpl}</span><br>
      <span class="c-cmd">python fetch.py</span>
    </div>
  </div>
</div>

<div class="stats">
  <div class="wrap">
    <div class="stats-inner">
      <span class="stat"><span class="stat-val">{n_stores}</span> {t_stat_stores}</span>
      <span class="stat">Python <span class="stat-val">3.8+</span></span>
      <span class="stat">{t_stat_source} <span class="stat-val">{domain}</span></span>
      <span class="stat">npm i <span class="stat-val">{t_stat_npm}</span></span>
      <span class="stat">{t_stat_lic} <span class="stat-val">MIT</span></span>
    </div>
  </div>
</div>

<div class="wrap">
  <section>
    <div class="sec-hdr">
      <span class="sec-title">{t_sec_title}</span>
      <span class="sec-count">{n_stores}</span>
    </div>
    <div class="grid">
{cards_html}
    </div>
  </section>
</div>

<footer>
  {t_footer} <a href="https://{domain}">{domain}</a> |
  <a href="https://github.com/{username}">GitHub</a>
</footer>

</body>
</html>"""


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Creeaza repo-urile GitHub pentru Shopilo (multi-country)"
    )
    parser.add_argument("--token",       required=True, help="GitHub Personal Access Token")
    parser.add_argument("--username",    required=True, help="GitHub username/org (ex: shopilo-ro)")
    parser.add_argument("--country",     default="ro",  help="Codul tarii: ro, de, fr, es, it (default: ro)")
    parser.add_argument("--dry-run",     action="store_true", help="Simuleaza fara sa creeze nimic")
    parser.add_argument("--only",        help="Creeaza doar repo-ul specificat (slug)")
    parser.add_argument("--update-html", action="store_true", help="Actualizeaza doar index.html cu luna curenta")
    parser.add_argument("--update-all",  action="store_true", help="Actualizeaza toate fisierele (README, HTML, scripts) in repo-urile existente")
    args = parser.parse_args()

    # ── Incarca config tara ──────────────────────────────────────────────────
    country_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"shopilo.{args.country}")
    if not os.path.isdir(country_dir):
        print(f"EROARE: Directorul '{country_dir}' nu exista.")
        print(f"Creeaza shopilo.{args.country}/stores.py cu COUNTRY_CONFIG si STORES.")
        sys.exit(1)

    stores_path = os.path.join(country_dir, "stores.py")
    spec = importlib.util.spec_from_file_location("country_stores", stores_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    config = mod.COUNTRY_CONFIG
    global SHOPILO_DOMAIN, STORE_PATH, MONTH_STR, T
    SHOPILO_DOMAIN = config["domain"]
    STORE_PATH     = config.get("store_path", "magazin")
    MONTH_STR      = config["months"][NOW.month]
    T              = config.get("t", {})
    stores_all     = mod.STORES

    # ── Autentificare ────────────────────────────────────────────────────────
    api = GitHubAPI(args.token, args.username)
    r = api.session.get("https://api.github.com/user")
    if r.status_code != 200:
        print(f"Token invalid: {r.json().get('message')}")
        sys.exit(1)
    print(f"Autentificat ca: {r.json()['login']} | Tara: {args.country} | Domain: {SHOPILO_DOMAIN}\n")

    stores = stores_all
    if args.only:
        stores = [s for s in stores_all if s[1] == args.only]
        if not stores:
            print(f"Nu am gasit repo-ul: {args.only}")
            sys.exit(1)

    # ── 0a. Mod update-all (actualizeaza TOATE fisierele in repo-uri existente) ─
    if args.update_all:
        print(f"Update ALL files for {len(stores)} stores ({MONTH_STR} {YEAR_STR})...\n")
        for i, (name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date) in enumerate(stores, 1):
            print(f"[{i:02d}/{len(stores)}] {slug}...", end=" ", flush=True)

            readme     = make_readme(name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date, args.username)
            fetch      = make_fetch_py(name, slug, shopilo_slug, args.username)
            index_js   = make_index_js(name, slug, shopilo_slug, args.username)
            pkg        = make_package_json(name, slug, shopilo_slug, args.username)
            req        = make_requirements()
            index_html = make_index_html(name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date, args.username)

            files = [
                ("README.md",        readme,      f"Update README {MONTH_STR} {YEAR_STR}"),
                ("index.html",       index_html,  f"Update page {MONTH_STR} {YEAR_STR}"),
                ("fetch.py",         fetch,       f"Update fetch script {MONTH_STR} {YEAR_STR}"),
                ("index.js",         index_js,    f"Update npm module {MONTH_STR} {YEAR_STR}"),
                ("package.json",     pkg,         f"Update package.json {MONTH_STR} {YEAR_STR}"),
                ("requirements.txt", req,         f"Update requirements {MONTH_STR} {YEAR_STR}"),
            ]

            all_ok = True
            for fname, content, commit_msg in files:
                if not api.update_file(slug, fname, content, commit_msg):
                    print(f"ERR:{fname}", end=" ")
                    all_ok = False
                time.sleep(0.3)

            print("OK" if all_ok else "PARTIAL")
            time.sleep(0.8)

        # Also update org index
        org_html = make_org_index_html(stores_all, args.username, config)
        pages_repo = f"{args.username}.github.io"
        print(f"\nUpdating {pages_repo} index...", end=" ")
        ok = api.update_file(pages_repo, "index.html", org_html, f"Update index {MONTH_STR} {YEAR_STR}")
        print("OK" if ok else "ERR")

        # Update org profile
        profile_readme = make_org_profile_readme(stores_all, args.username, config)
        print(f"Updating .github profile...", end=" ")
        ok = api.update_file(".github", "profile/README.md", profile_readme, f"Update profile {MONTH_STR} {YEAR_STR}")
        print("OK" if ok else "ERR")

        print("\nDone! All files updated.")
        sys.exit(0)

    # ── 0b. Mod update-html (folosit de GitHub Action lunar) ──────────────────
    if args.update_html:
        print(f"Update index.html pentru {len(stores)} magazine ({MONTH_STR} {YEAR_STR})...\n")
        for i, (name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date) in enumerate(stores, 1):
            print(f"[{i:02d}/{len(stores)}] {slug}...", end=" ", flush=True)
            html = make_index_html(name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date, args.username)
            ok = api.update_file(slug, "index.html", html, f"Update {MONTH_STR} {YEAR_STR}")
            print("OK" if ok else "EROARE")
            time.sleep(0.5)
        print("\nGata! Toate paginile au fost actualizate.")
        sys.exit(0)

    # ── 1. Repo-uri individuale ──────────────────────────────────────────────
    print(f"Creez {len(stores)} repo-uri individuale...\n")

    for i, (name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date) in enumerate(stores, 1):
        print(f"[{i:02d}/{len(stores)}] {slug}...", end=" ", flush=True)

        if args.dry_run:
            print("DRY RUN - skip")
            continue

        ok, msg = api.create_repo(slug, T["common_repo_desc"].format(store=name, domain=SHOPILO_DOMAIN))
        if not ok:
            print(f"EROARE: {msg}")
            continue
        print(f"repo {msg}", end=" | ", flush=True)

        time.sleep(0.5)

        readme     = make_readme(name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date, args.username)
        fetch      = make_fetch_py(name, slug, shopilo_slug, args.username)
        index_js   = make_index_js(name, slug, shopilo_slug, args.username)
        pkg        = make_package_json(name, slug, shopilo_slug, args.username)
        req        = make_requirements()
        index_html = make_index_html(name, slug, shopilo_slug, ex_code, ex_disc, ex_desc, ex_date, args.username)

        files = [
            ("README.md",        readme,      "Add README"),
            ("index.html",       index_html,  "Add GitHub Pages store page"),
            ("fetch.py",         fetch,       "Add Python fetch script"),
            ("index.js",         index_js,    "Add npm module"),
            ("package.json",     pkg,         "Add package.json"),
            ("requirements.txt", req,         "Add requirements"),
        ]

        all_ok = True
        for fname, content, commit_msg in files:
            if not api.create_file(slug, fname, content, commit_msg):
                print(f"EROARE la {fname}", end=" ")
                all_ok = False
            time.sleep(0.3)

        time.sleep(0.5)
        api.enable_pages(slug)

        print("OK" if all_ok else "PARTIAL")
        time.sleep(1.2)

    # ── 2. Repo GitHub Pages principal (username.github.io) ──────────────────
    pages_repo = f"{args.username}.github.io"
    print(f"\nCreez pagina GitHub Pages: {pages_repo}...", end=" ", flush=True)

    if not args.dry_run:
        ok, msg = api.create_repo(pages_repo, T["common_pages_desc"].format(domain=SHOPILO_DOMAIN))
        print(f"repo {msg}", end=" | ", flush=True)

        time.sleep(0.5)

        # Genereaza org page din date (nu citeste din disk)
        org_html = make_org_index_html(stores_all, args.username, config)
        if api.create_file(pages_repo, "index.html", org_html, "Add GitHub Pages index"):
            print("index.html OK", end=" | ")

        # Uploadeaza scriptul de update si GitHub Action
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "create_repos.py")
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()
        if api.create_file(pages_repo, "create_repos.py", script_content, "Add update script"):
            print("create_repos.py OK", end=" | ")

        workflow_yml = make_workflow_yml(args.username, args.country)
        if api.create_file(pages_repo, ".github/workflows/monthly-update.yml", workflow_yml, "Add monthly update action"):
            print("GitHub Action OK", end=" | ")

        time.sleep(1)
        api.enable_pages(pages_repo)
        print("Pages activat")
    else:
        print("DRY RUN - skip")

    # ── 3. Org profile README (.github repo → github.com/username) ───────────
    profile_repo = ".github"
    print(f"\nCreez org profile: {profile_repo}...", end=" ", flush=True)

    if not args.dry_run:
        ok, msg = api.create_repo(profile_repo, T["common_profile_desc"].format(username=args.username))
        print(f"repo {msg}", end=" | ", flush=True)
        time.sleep(0.5)

        profile_readme = make_org_profile_readme(stores_all, args.username, config)
        if api.create_file(profile_repo, "profile/README.md", profile_readme, "Add org profile README"):
            print("profile/README.md OK")
        else:
            print("EROARE profile/README.md")
    else:
        print("DRY RUN - skip")

    print(f"""
Gata!
  Org profile:  https://github.com/{args.username}
  GitHub Pages: https://{args.username}.github.io
  Magazine:     {len(stores_all)} ({SHOPILO_DOMAIN})

GitHub Pages poate dura 1-2 minute sa fie live dupa activare.
""")


if __name__ == "__main__":
    main()
