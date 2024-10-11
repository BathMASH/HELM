import os
from bs4 import BeautifulSoup

code = """<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "45c34618a8294826b85725434b26e3db"}'></script><!-- End Cloudflare Web Analytics -->"""
dirs = os.walk('.')
for d in dirs:
    curr_dir = d[0]
    for file in d[2]:
        if file.endswith('html'):
            curr_file = os.path.join(curr_dir,file)
            print('snippet added: ',curr_file)
            with open(curr_file, "r", encoding='utf-8') as infile:
                soup = BeautifulSoup(infile,"html.parser")
            body = soup.body
            snippet = BeautifulSoup(code,'html.parser')
            body.append(snippet)
            with open(curr_file, "w", encoding='utf-8') as file:
                file.write(str(soup))