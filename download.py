import requests
from bs4 import BeautifulSoup
import re
import json
import sys
import concurrent.futures
from os import path as ospath
import os
from pathlib import Path
from clint.textui import progress
from resources import utility
from resources.stopwatch import Timer

headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '3600',
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0'
}

WATCHTVSERIES_ADMIN = "https://watchtvseries.one/wp-admin/admin-ajax.php"
MAX_WORKERS = 20
MAX_RETRIES = 5


def download_show(url, retry_num):
    print("Download retry " + str(retry_num) + ": %s" % url)
    req = requests.get(url, headers)
    show_page_soup = BeautifulSoup(req.content, 'html.parser')
    show_name = get_show_name(show_page_soup)

    tab_contents = show_page_soup.findAll('div', {'class': 'tabcontent'})

    deleted_files = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as download_executor:
        num_seasons = len(tab_contents)
        download_futures = []
        for i in range(0, num_seasons):
            content = tab_contents[i]
            season = num_seasons - i
            download_location = DOWNLOAD_ROOT + show_name + '/Season ' + str(season) + '/'
            Path(download_location).mkdir(parents=True, exist_ok=True)
            links = content.findAll('a', href=True)
            num_eps = len(links)

            futures = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for j in range(0, num_eps):
                    link = links[j]
                    ep = num_eps - j
                    name = show_name + '_S' + str(season) + '_E' + str(ep) + '.mp4'
                    if ospath.exists(download_location + name):
                        continue
                    url = link['href']
                    future = executor.submit(scrape_download_link, url)
                    futures.append((name, future))

            # get results
            download_list = []
            for name, future in futures:
                download_link = future.result()
                download_list.append((name, download_link))

            # download mp4 from google
            for name, download_link in download_list:
                future = download_executor.submit(download_file, name, download_link, download_location)
                download_futures.append(future)

        print("Ready to download files")
        for future in download_futures:
            result = future.result()
            if result:
                deleted_files = True
    if deleted_files:
        if retry_num < MAX_RETRIES:
            download_show(url, retry_num + 1)
        else:
            print("Out of retries. Moving onto next show.")


def download_file(name, download_link, download_location):
    timer = Timer()
    timer.start()
    r = requests.get(download_link, stream=True)
    path = download_location + name
    with open(path, 'wb') as output_file:
        total_length = int(r.headers.get('content-length'))
        for chunk in progress.bar(r.iter_content(chunk_size=1024), expected_size=(total_length / 1024) + 1):
            if chunk:
                output_file.write(chunk)
                output_file.flush()
        output_file.close()

    # if file too small (under 2k), delete it
    if ospath.getsize(path) < 2 * 1024:
        print("Deleting file because too small: " + name)
        os.remove(path)
        return False
    else:
        print(timer.stop("Finished downloading " + name + " in: "))
        return True


def scrape_download_link(url):
    if 'gounlimited.to' in url:
        download_link = process_gounlimited(url)
    elif 'watchtvseries' in url:
        download_link = process_watchtvseries(url)
    else:
        print("%s is neither gounlimited nor watchtvseries" % url)
        download_link = None
    return download_link


def process_gounlimited(url):
    req = requests.get(url, headers)

    js_soup = BeautifulSoup(req.text, 'html.parser')
    script_tag = js_soup.findAll("script")
    for script in script_tag:
        if len(script.contents) == 0:
            continue
        text = script.contents[0]
        if "function(p,a,c,k,e,d)" in text:
            text = text.strip()
            unpacked = eval('utility.unpack' + text[text.find('}(') + 1:-1])
            return re.findall(r'src:"(.+?)"', unpacked)[0]


def process_watchtvseries(url):
    req = requests.get(url, headers)
    soup = BeautifulSoup(req.text, 'html.parser')
    id = soup.find('input', {'name': 'id'})['value']
    query_params = {'action': 'getvideo', 'nb': 0, 'b': id}
    response = requests.get(WATCHTVSERIES_ADMIN, params=query_params).content
    video_json = json.loads(response)
    if video_json['status'] == 'success':
        video_html = video_json['payload']
        video_soup = BeautifulSoup(video_html, 'html.parser')
        link = video_soup.find('a', href=True)['href']
        return process_gounlimited(link)


def get_show_name(show_page_soup):
    name = show_page_soup.find('meta', {'itemprop': 'name'})['content']

    # normalize names
    return name.replace(' ', '_')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Please provide download file name")
        exit(0)

    DOWNLOAD_FILE = sys.argv[1]
    if not ospath.exists(DOWNLOAD_FILE):
        print("Please make sure file exists")
        exit(0)

    if not ospath.exists(sys.argv[1]):
        print("Please make sure file exists")
        exit(0)

    DOWNLOAD_ROOT = sys.argv[2]
    with open(DOWNLOAD_FILE, "r") as f:
        for line in f:
            download_show(line, 0)
