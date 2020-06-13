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

headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '3600',
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0'
}

WATCHTVSERIES_ADMIN = "https://watchtvseries.one/wp-admin/admin-ajax.php"


def download_show(url):
    print("Getting %s" % url)
    req = requests.get(url, headers)
    print("Parse %s" % url)
    show_page_soup = BeautifulSoup(req.content, 'html.parser')
    show_name = get_show_name(show_page_soup)

    tab_contents = show_page_soup.findAll('div', {'class': 'tabcontent'})
    num_seasons = len(tab_contents)
    for i in range(0, num_seasons):
        content = tab_contents[i]
        season = num_seasons - i
        download_location = DOWNLOAD_ROOT + show_name + '/Season ' + str(season) + '/'
        print("Creating %s if not exist" % download_location)
        Path(download_location).mkdir(parents=True, exist_ok=True)

        links = content.findAll('a', href=True)
        num_eps = len(links)

        print("Creating futures for season %s" % str(seasons))
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            for j in range(0, num_eps):
                link = links[j]
                ep = num_eps - j
                name = show_name + '_S' + str(season) + '_E' + str(ep) + '.mp4'
                print("File name: %s" % name)
                if ospath.exists(download_location + name):
                    print("Skipping %s because file already exists" % name)
                url = link['href']
                future = executor.submit(scrape_download_link, url)
                futures.append((name, future))

        print("Creating download_list")
        # get results
        download_list = []
        for name, future in futures:
            download_link = future.result()
            download_list.append((name, download_link))

        print("Downloading files")
        deleted_files = False
        # download mp4 from google
        for name, download_link in download_list:
            print("Downloading: %s" % name)
            r = requests.get(download_link, stream=True)
            path = download_location + name
            with open(path, 'wb') as f:
                total_length = int(r.headers.get('content-length'))
                for chunk in progress.bar(r.iter_content(chunk_size=1024), expected_size=(total_length / 1024) + 1):
                    if chunk:
                        f.write(chunk)
                        f.flush()

            # if file too small (under 2k), delete it
            if ospath.getsize(path) < 2 * 1024:
                os.remove(path)
                deleted_files = True

        if deleted_files:
            raise Exception("Downloaded files that were empty")


def scrape_download_link(url):
    if 'gounlimited.to' in url:
        download_link = process_gounlimited(url)
    elif 'watchtvseries' in url:
        download_link = process_watchtvseries(url)
    else:
        download_link = None
    return download_link


def process_gounlimited(url):
    req = requests.get(url, headers)
    js_soup = BeautifulSoup(req.text, 'html.parser')
    script_tag = js_soup.findAll("script")
    for script in script_tag:
        text = script.text
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
    f = open(DOWNLOAD_FILE, "r")
    exceptions = 1
    retries = 0
    MAX_RETRIES = 5
    while exceptions > 0 | retries < MAX_RETRIES:
        retries += 1
        exceptions = 0
        for line in f:
            try:
                download_show(line)
            except:
                exceptions += 1
                print("Failed to download show: %s" % line)
