import os
from os.path import join, dirname

from dotenv import load_dotenv
# loading .env file
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)
WEB_DRIVER_LOCATION = os.environ.get("WEB_DRIVER_LOCATION")
HOST = os.environ.get("HOST")
DBUSER = os.environ.get("DBUSER")
DBPASSWD = os.environ.get("DBPASSWD")

from multiprocessing import Process, Value, Lock, Manager
import multiprocessing

import re
import io
import pathlib
import time
from datetime import datetime
import threading
import psycopg2
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
import url
from urllib.parse import urlparse
from urllib.parse import urljoin
from urllib.request import urlopen
from reppy import Robots
import socket
from PIL import Image
import hashlib

TIMEOUT = 5
USERAGENT = 'fri-wier-vipavska-burja'
RENDERTIMEOUT = 5


# 'http://83.212.82.40/testJsHref/' -> for testing onclick href
SEEDARRAY = ['https://gov.si/', 'https://evem.gov.si/', 'https://e-uprava.gov.si/', 'https://e-prostor.gov.si/']

chrome_options = Options()
# If you comment the following line, a browser will show ...
chrome_options.add_argument("--headless")
# Adding a specific user agent
chrome_options.add_argument("user-agent="+USERAGENT)
# disable console.log
chrome_options.add_argument("--log-level=3")
# ignore SSL certificate errors
chrome_options.add_argument("--ignore-certificate-errors")

driver = webdriver.Chrome(WEB_DRIVER_LOCATION, options=chrome_options)
driver.set_page_load_timeout(30)

lock = Lock()

mozneKoncnice = []

def databasePutConn(stringToExecute, params=()):
    #with lock:
    conn = psycopg2.connect(host=HOST, user=DBUSER, password=DBPASSWD)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(stringToExecute, params)
    cur.close()
    conn.close()

def databaseGetConn(stringToExecute, params=()):
    #with lock:
    conn = psycopg2.connect(host=HOST, user=DBUSER, password=DBPASSWD)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(stringToExecute, params)
    answer = cur.fetchall()
    cur.close()
    conn.close()
    return answer

def initFrontier(seed):
    #print("Inicializiram Frontier")
    databasePutConn("TRUNCATE crawldb.site, crawldb.page RESTART IDENTITY CASCADE;")  # pobrisi vse vnose iz baze
    postgres_insert_query = "INSERT INTO crawldb.page (page_type_code, url) VALUES "
    for domain in seed:
        postgres_insert_query = postgres_insert_query + "('FRONTIER', '" + domain + "'),"
    databasePutConn(postgres_insert_query[:-1])

def initFrontierProcessing():
    databasePutConn("UPDATE crawldb.page SET page_type_code='FRONTIER' WHERE page_type_code='PROCESSING'")

def initCrawler(seedArray):
    numberFronteir = databaseGetConn("SELECT COUNT(*) FROM crawldb.page WHERE page_type_code='FRONTIER'")[0][0]
    if numberFronteir == 0:
        initFrontier(seedArray)  # prvi start pajka
    else:
        initFrontierProcessing()  # restart pajka

def initDataTypes():
    global mozneKoncnice
    dbTypes = databaseGetConn('SELECT * FROM crawldb.data_type ')
    for dbType in dbTypes:
        mozneKoncnice.append(dbType[0].lower())

def checkRootSite(domain):
    data = databaseGetConn("SELECT * FROM crawldb.site WHERE domain='" + domain + "'")
    return data

def fetchPageContent(domain, webAddress, driver, delayRobots, dictIpTime):
    del driver.requests  # pobrisi requeste za nazaj, ker nas zanimajo samo trenutni!
    
    print("delayRobots",delayRobots)
    print("dictIpTime",dictIpTime)
    
    try:
        naslovIP = socket.gethostbyname(domain)
    except:
        #print("ERR_NAME_NOT_RESOLVED")
        return None, 417, None
    
    if(delayRobots.get(naslovIP) is not None):
        delayTime = delayRobots.get(naslovIP)
    else:
        delayTime = TIMEOUT
    
    timeStampIzDict = dictIpTime.get(naslovIP)
    if timeStampIzDict is None:
        timeStampIzDict = time.time()
    elif (time.time() - timeStampIzDict) < delayTime:
        time.sleep(delayTime - (time.time() - timeStampIzDict))
    
    try:
        driver.get(webAddress)
    except:
        return None, 417, None
    
    #dictIpTime = {naslovIP: time.time()}
    dictIpTime[naslovIP] = time.time()
    
    # Timeout needed for Web page to render
    time.sleep(RENDERTIMEOUT)
    
    try:
        if hasattr(driver, 'page_source'): # smo dobili nazaj content?
            content = driver.page_source
            # print(f"Retrieved Web content (truncated to first 900 chars): \n\n'\n{html[:900]}\n'\n")
            start_time = time.time()
            
            if hasattr(driver.requests[0], 'response'): # did we get response back??
                steviloResponse = -1
                responseContent = 0
                responseStatusCode = 0
                
                for request in driver.requests:
                    if request.response:
                        #print( steviloResponse, request.url, request.response.status_code, request.response.headers['Content-Type'] )
                        steviloResponse += 1
                        if request.response.headers['Content-Type'] is not None and 'text/html' in request.response.headers['Content-Type']:
                            responseContent = steviloResponse
                
                if driver.requests[responseStatusCode].response is not None:
                    return content, driver.requests[responseStatusCode].response.status_code, driver.requests[responseContent].response.headers['Content-Type']
            
            #for request in driver.requests:
            #    if request.response:
            #         print( request.url, request.response.status_code, request.response.headers['Content-Type'] )
            
            #print("\nFetch: No status code code!\n")
            #return content, 200, None
    except:
        pass
    
    return None, 417, None

def urlCanonization(inputUrl):
    outputUrl = url.parse(inputUrl).strip().defrag().canonical().abspath().utf8
    return outputUrl.decode("utf-8")

def saveUrlToDB(inputUrl, currPageId):
    #koncniceSlik = ['.jpg', '.png', '.gif', '.webm', '.weba', '.webp', '.tiff']
    #if pathlib.Path(os.path.basename(urlparse(inputUrl).path)).suffix in koncniceSlik: # ce je slika
    #    pass
    #else:
    # preveri če je link na *.gov.si, drugace se ga ne uposteva
    domena = urlparse(inputUrl).netloc
    #if re.match(r'.*([\.]gov.si(^$|[\/])).*', domena):
    if re.match(r'.*((^|[\.])gov.si)', domena):
        parsed_url = urlCanonization(inputUrl)  # URL CANONIZATION
        try:
            #newPageId = databaseGetConn("INSERT INTO crawldb.page (page_type_code, url) VALUES ('FRONTIER', %s) RETURNING id", (parsed_url,))
            newPageId = databaseGetConn("INSERT INTO crawldb.page (page_type_code, url) VALUES ('FRONTIER', %s) ON CONFLICT(url) DO UPDATE SET url=%s RETURNING id ", (parsed_url,parsed_url))
            databasePutConn("INSERT INTO crawldb.link (from_page,to_page) VALUES (%s, %s) ", (currPageId,newPageId[0][0]))
        except:
            #print("URL ze v DB")  # hendlanje podvojitev
            pass

def getHrefUrls(content, currPageId):
    #urls = []
    for element in driver.find_elements_by_tag_name("a"):
        href = element.get_attribute('href')
        if href:  # is href not None?
            #urls.append(href)
            saveUrlToDB(href, currPageId)  # save URLs to DB

def getJsUrls(content, currPageId):
    #urls = []
    for element in driver.find_elements_by_xpath("//*[@onclick]"): # find all elements that have attributre onclick
        onclick = element.get_attribute('onclick')
        result = re.search(r'(\"|\')(.*)(\"|\')', onclick)
        #urls.append(result.group(2))
        if result:
            if result.group(2) is not None:
                saveUrlToDB(result.group(2), currPageId)  # save URLs to DB

def getImgUrls(content, pageId, timestamp):
    for element in driver.find_elements_by_tag_name("img"):
        src = element.get_attribute('src')
        if src:
            if "data:image" in src: # is image encoded in src field:
                if element.get_attribute('alt'):
                    databasePutConn("INSERT INTO crawldb.image (page_id, filename, content_type, data, accessed_time) VALUES (%s,%s,%s,%s,%s)", (pageId, 'Alt: '+element.get_attribute('alt'), 'data:image', src, timestamp))
                else:
                    databasePutConn("INSERT INTO crawldb.image (page_id, filename, content_type, data, accessed_time) VALUES (%s,%s,%s,%s,%s)", (pageId, 'No name', 'data:image', src, timestamp))
                    
            else: # is image just url
                saveImageFromUrl(src, pageId, timestamp)
                """parsed_url_img = urlCanonization(src)
                imageName = os.path.basename(urlparse(parsed_url_img).path)
                #print("SLIKA: " + imageName)
                # detect image format
                if pathlib.Path(imageName).suffix in '.svg':
                    # data?
                    try:
                        databasePutConn("INSERT INTO crawldb.image (page_id, filename, content_type, accessed_time) VALUES (%s,%s,%s,%s)", (pageId, imageName, 'SVG', timestamp))
                    except:
                        # if link too long
                        pass
                else:
                    try:
                        pil_im = Image.open(urlopen(parsed_url_img)) 
                        b = io.BytesIO()
                        pil_im.save(b, pil_im.format)
                        imageBytes = b.getvalue()
                        databasePutConn("INSERT INTO crawldb.image (page_id, filename, content_type, data, accessed_time) VALUES (%s,%s,%s,%s,%s)", (pageId, imageName, pil_im.format, imageBytes, timestamp))
                    except:
                        pass # ulovi napako SSL"""

def saveImageFromUrl(url, pageId, timestamp):
    parsed_url_img = urlCanonization(url)
    imageName = os.path.basename(urlparse(parsed_url_img).path)
    #print("SLIKA: " + imageName)
    # detect image format
    if pathlib.Path(imageName).suffix in '.svg':
        # data?
        try:
            databasePutConn("INSERT INTO crawldb.image (page_id, filename, content_type, accessed_time) VALUES (%s,%s,%s,%s)", (pageId, imageName, 'SVG', timestamp))
        except:
            # if link too long
            pass
    else:
        try:
            pil_im = Image.open(urlopen(parsed_url_img)) 
            #b = io.BytesIO()
            #pil_im.save(b, pil_im.format)
            #imageBytes = b.getvalue()
            databasePutConn("INSERT INTO crawldb.image (page_id, filename, content_type, accessed_time) VALUES (%s,%s,%s,%s)", (pageId, imageName, pil_im.format, timestamp))
        except:
            # catch errors (SSL)
            pass

def getNextUrl(lock):
    # pridobi naslednji URL
    with lock:
        
        sitesProcessed = databaseGetConn("SELECT COUNT(*) FROM crawldb.page WHERE page_type_code!='FRONTIER'")
        if sitesProcessed[0][0] > 55500:
            return None
        
        sitesLocked = databaseGetConn("SELECT url FROM crawldb.page WHERE page_type_code='PROCESSING'")
        stringUrls = ""
        for siteUrl in sitesLocked:
            stringUrls += " AND url NOT LIKE \'%%"+urlparse(siteUrl[0]).netloc+"%%\'"
            
        url = databaseGetConn("SELECT id,url FROM crawldb.page WHERE page_type_code='FRONTIER'"+stringUrls+" ORDER BY id LIMIT 1")
        if not url:
            return None
        # lock this url in frontier
        databasePutConn("UPDATE crawldb.page SET page_type_code='PROCESSING' WHERE id=%s AND urL=%s", (url[0][0], url[0][1]))
        return url[0]

def contentTypeCheck(link, contentType):
    global mozneKoncnice
    if contentType is not None:
        if 'text/html' in contentType: # ugotavljanje iz content type
            return 'HTML'
        else:
            return 'BINARY'
    return checkLinkForBinary(link)
    #return 'ERROR'

def checkLinkForBinary(link):
    global mozneKoncnice
    mozneImage = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'weba', 'bmp', 'tiff', 'svg']
    if link is not None: # ugotavljanje iz linka
        koncninca = pathlib.Path(os.path.basename(urlparse(link).path)).suffix.lower().replace('.','')
        if koncninca in mozneKoncnice:
            return 'BINARY', koncninca.upper()
        elif koncninca in mozneImage:
            return 'BINARY', 'IMAGE'
    return 'HTML', ''

def robotsValidate(content):
    if content:
        if "not found" not in content.lower() and 'user-agent:' in content.lower():
            return True
    return False

# delovna funkcija -> ki predstavlja en proces
def process(nextUrl, lock, delayRobots, dictIpTime):
    initDataTypes()
    urlId = None
    while urlId is None:
        time.sleep(2)
        urlId = getNextUrl(lock)  # take first url from frontier (DB)
    
    while urlId is not None:  # MAIN LOOP
        nextUrl = urlId[1]
        parsedUrl = urlparse(nextUrl)
        
        print("PID:",'{0:06}'.format(os.getpid())," Next URL:",nextUrl)
        
        robots = None
        domain = parsedUrl.netloc
        if 'www.' in domain:
            domain = domain.replace('www.','')
        if not checkRootSite(domain):  # site unknown (domain not in sites)
            robotsUrl = urljoin(parsedUrl.scheme+'://'+domain, 'robots.txt') # generate robots path
            robotContent, httpCode, contType = fetchPageContent(domain, robotsUrl, driver, delayRobots, dictIpTime)
            
            if httpCode < 400 and robotsValidate(robotContent):
                robotContent = driver.find_elements_by_tag_name("body")[0].text  # robots.txt -> get only text, without html tags
                robots = Robots.parse(robotsUrl, robotContent)
                
                for sitemap in robots.sitemaps:
                    sitemapContent, httpCode, contType = fetchPageContent(domain, sitemap, driver, delayRobots, dictIpTime)
                
                if robots.sitemaps: # robots & sitemap present
                    databasePutConn("INSERT INTO crawldb.site (domain, robots_content, sitemap_content) VALUES (%s,%s,%s)", (domain, robotContent, sitemapContent))
                else: # only robots.txt present
                    databasePutConn("INSERT INTO crawldb.site (domain, robots_content) VALUES (%s,%s)", (domain, robotContent))
                
                if robots.agent('*').delay:  # robots & delay present
                    delayRobots[socket.gethostbyname(domain)] = robots.agent('*').delay
                if robots.agent(USERAGENT).delay:  # robots & delay present
                    delayRobots[socket.gethostbyname(domain)] = robots.agent(USERAGENT).delay
                
            else: # no robots
                databasePutConn("INSERT INTO crawldb.site (domain) VALUES (%s)", (domain,))
            # link page with site
            databasePutConn("UPDATE crawldb.page SET site_id=(SELECT id FROM crawldb.site WHERE domain=%s) WHERE url=%s", (domain, nextUrl))
        else: # site known
            # link page with site
            databasePutConn("UPDATE crawldb.page SET site_id=(SELECT id FROM crawldb.site WHERE domain=%s) WHERE url=%s", (domain, nextUrl))
            # load robots from DB
            robotContent = databaseGetConn("SELECT robots_content FROM crawldb.site WHERE domain=%s", (domain,))[0][0]
            if robotContent is not None:
                robots = Robots.parse(nextUrl + '/robots.txt', robotContent)
                if robots.agent('*').delay:  # robots & delay present
                    delayRobots[socket.gethostbyname(domain)] = robots.agent('*').delay
                if robots.agent(USERAGENT).delay:  # robots & delay present
                    delayRobots[socket.gethostbyname(domain)] = robots.agent(USERAGENT).delay
            else:
                robots = None
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if robots is None or robots.allowed(nextUrl, USERAGENT) : # does robots allow us to go on this link?
            linkType,binaryType = checkLinkForBinary(nextUrl)
            # preveri ali ima stran koncnico ...
            if linkType == 'HTML':
                # download page content
                content, httpCode, contentType = fetchPageContent(domain, nextUrl, driver, delayRobots, dictIpTime)
                
                # temp url, kam smo bli preusmerjeni ?
                if content is None or  httpCode == 417: # prazen content
                    databasePutConn("UPDATE crawldb.page SET page_type_code='ERROR', accessed_time=%s WHERE id=%s AND urL=%s", (timestamp, urlId[0], urlId[1]))
                else:
                    #contentType2 = contentTypeCheck(nextUrl, contentType) #ugotovi kakšen tip je ta content
                    # hash contenta
                    hashContent = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    # ugotovi duplicate
                    numberHash = databaseGetConn("SELECT COUNT(*) FROM crawldb.page WHERE hash=%s", (hashContent,))[0][0]
                    
                    if numberHash == 0: # ce je podvojena stran, shrani hash in continue
                    #if numberHash == 0 or contentType2 == 'HTML': # ce je podvojena stran, shrani hash in continue
                        #if contentType is not None and 'text/html' in contentType:
                        #if contentType2 == 'HTML':
                        getHrefUrls(content, urlId[0]) # get all href links
                        getJsUrls(content, urlId[0]) # get all JS links
                        getImgUrls(content, urlId[0], timestamp) # get all img links
                        databasePutConn("UPDATE crawldb.page SET html_content=%s, http_status_code=%s, page_type_code='HTML', accessed_time=%s, hash=%s WHERE id=%s AND urL=%s", (content, httpCode, timestamp, hashContent, urlId[0], urlId[1]))
                        #elif contentType2 == 'BINARY':
                        #    databasePutConn("UPDATE crawldb.page SET http_status_code=%s, page_type_code='BINARY', accessed_time=%s WHERE id=%s AND urL=%s", (httpCode, timestamp, urlId[0], urlId[1]))
                        #    databasePutConn("INSERT INTO crawldb.page_data SET (page_id, data_type_code) VALUES (%s,%s,%s)", (urlId[0],binaryType))
                        
                    else: # duplicated page
                        databasePutConn("UPDATE crawldb.page SET html_content=%s, http_status_code=%s, page_type_code='DUPLICATE', accessed_time=%s, hash=%s WHERE id=%s AND urL=%s", (content, httpCode, timestamp, hashContent, urlId[0], urlId[1]))
            else: # BINARY page -> detected from link
                # http_status_code=%s,  httpCode, 
                databasePutConn("UPDATE crawldb.page SET page_type_code='BINARY', accessed_time=%s WHERE id=%s AND urL=%s", (timestamp, urlId[0], urlId[1]))
                 
                if binaryType == 'IMAGE':
                    saveImageFromUrl(urlId[1], urlId[0], timestamp)
                else:
                    databasePutConn("INSERT INTO crawldb.page_data (page_id, data_type_code) VALUES (%s,%s)", (urlId[0],binaryType))
               
        else: # ni dovoljeno v robots
            databasePutConn("UPDATE crawldb.page SET page_type_code='NOTALOWED', accessed_time=%s WHERE id=%s AND urL=%s", (timestamp, urlId[0], urlId[1]))
        
        urlId = getNextUrl(lock)  # next url from frontier (DB)
    
    return True


# zagon programa
def run():
    PROCESSES = multiprocessing.cpu_count() - 1
    PROCESSES = int(input("Enter number of processes: "))
    print(f"Running with {PROCESSES} processes!")
    
    manager = Manager()
    dictIpTime = manager.dict()
    delayRobots = manager.dict()
    
    initCrawler(SEEDARRAY)
    
    start = time.time()
    
    nextUrls = ['']
    procs = [Process(target=process, args=(nextUrls,lock, delayRobots, dictIpTime)) for i in range(PROCESSES)] # ustvarjanje procesov
    for p in procs: p.start()
    for p in procs: p.join()
    
    driver.close()
    print(f"FINISHED: Time taken = {time.time() - start:.10f}")

if __name__ == "__main__":
    #initFrontier(SEEDARRAY) # clear DB !!
    run()


# IZ DISCORDA:
# kateri link se zapiše v bazo ob redirectu. Oba ali samo enega. Če ima prvi link code 302, zapišemo v bazo, nov zapis v bazi z drugim urljem pa nosi content
# sitemap če se upošteva
