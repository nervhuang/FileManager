import urllib.request, json
url='https://api.github.com/repos/nervhuang/FileManager/actions/runs?per_page=5'
with urllib.request.urlopen(url) as r:
    data=json.load(r)
for run in data.get('workflow_runs',[]):
    print('id:{id} status:{status} conclusion:{conclusion} event:{event} url:{url}'.format(
        id=run.get('id'), status=run.get('status'), conclusion=run.get('conclusion'), event=run.get('event'), url=run.get('html_url')
    ))
