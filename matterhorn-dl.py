import argparse
from getpass import getpass
from os import path

import requests
import sys
from lxml import etree
from lxml import html as lxmhtml
from unidecode import unidecode

__version__ = "0.4"

"""
Download lecturetube video from given source. Downloads via wget. Downloads will always be resumed.
Can download videos from
    - single ltcc view page
    - single moodle view page
    - moodle course page
Not properly tested. No known bugs. Give correct input -> profit.
"""


# BEWARE: html is of lxml.html type, not string! #


# possibly colors dont work on windows.
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class IShouldReallyStopRN(Exception):
    pass


class NoVideoFound(Exception):
    pass


# remember this is not secure in anyway. its just the tuwel login though so......
# OVERWRITTEN BY ANYTHING YOU PUT INTO data.py
auth = {
    "name": "",  # martrikel nr
    "pw": "",  # tu pw
    "app": "36"  # required
}

# import login data from data.py file (unsecure)
# IF data.py CONTAINS VALUES WILL OVERWRITE ANYTHING SET PREVIOUSLY
try:
    pr_info("Trying to fetch login data")
    import data as login

    if login.name is "" or login.pw is "":
        raise AttributeError
    auth['name'] = login.name
    auth['pw'] = login.pw
except (ImportError, AttributeError) as e:
    # loading from external didn't work. doesn't matter
    pr_info("Fetching login data failed. No Data set.")


def pr_verbose(message):
    """
    Print [INFO] messages (yellow) if verbose is turned on
    """
    if args.verbose:
        pr_info("[INFO] " + message)


def pr_info(message):
    """
    Print message in yellow
    """
    print(Colors.WARNING + message + Colors.ENDC)


def pr_error(message):
    """
    Print message in red
    """
    print(Colors.FAIL + message + Colors.ENDC)


def login():
    """
    Attempt to login to TUWEL. If data not set asks user for name and password.
    :return: the Session if login worked else None
    """
    login_url = "https://iu.zid.tuwien.ac.at/AuthServ.authenticate?app=36"
    if auth["name"] is "" or auth["pw"] is "":
        pr_verbose("You can set your login (unsecure) at the top of this file in the 'auth' dict.")
    if auth["name"] is "":
        auth["name"] = input("Your TU username (matnr): ")
    if auth["pw"] is "":
        # getPass can't stop PyCharm from outputting your pw. It warns about this. When in doubt, use proper terminal.
        auth["pw"] = getpass(prompt="Your TU password: ")

    session = requests.session()
    result = session.post(
        login_url,
        data=auth,
        headers=dict(referer=login_url)
    )
    if "Sie sind nicht angemeldet." in result.text:
        print("nicht ang")
        return None
    return session


def get_html(session, url):
    """
    Get the HTML of the url and return it as lxml.html
    :param url: the page
    :param session: the Session
    :return: the html as lxml.html
    """
    result = session.get(
        url,
        headers=dict(referer=url)
    )
    tree = lxmhtml.fromstring(result.content)
    return tree


def check_access(session):
    """
    Checks if the user currently has access to Lecturetube. Lecturetube is only available in the TU Network.
    :param session: the Session
    :return: True of False
    """
    url = "http://mh-engage.ltcc.tuwien.ac.at/index.html"
    result = session.get(
        url,
        headers=dict(referer=url)
    )
    if "ZUGRIFF VERWEIGERT" in result.text or "ACCESS DENIED" in result.text:
        return False
    return True


def get_pages_from_course(html):
    """
    Gets all anchor tags in the #region-main id of given html.
    If they contain a href thats propably a lecture its appended to the return
    :param html: html to search through
    :return: all found urls probably linking to a lecture
    """
    ret = []
    for anchor in html.cssselect('#region-main a'):
        href = anchor.get('href')
        # get all <a> with href linking to a lecture video (from overview page)
        if "mod/page/view.php" in href:
            # pr_verbose(href)
            ret.append(href)
    if len(ret) < 1:
        raise NoVideoFound("Couldn't find any view Pages on this Course URL")
    return ret


def get_view_url_from_single_page(html):
    """
    Gets the src of the first iFrame and its title in given html
    :param html: the html to search through
    :return: the found url, the found title
    """
    ret = []
    for iframe in html.cssselect('iframe'):
        src = iframe.get('src')
        # get all iframes linking to a lecture
        if "mh-engage.ltcc.tuwien.ac.at/engage/ui/embed" in src:
            # pr_verbose(src)
            ret.append(src)
    titles = html.cssselect("#region-main h2")  # get tuwel video title (more descriptive than ltcc video title)
    if not len(titles) > 0:
        le_title = ""
    else:
        le_title = titles[0].text

    # not sure this suffices to stop fails when no iframe is found TODO test this out
    if len(ret) < 1:
        ret[0] = ""
    # more than 1 video per moodle view page possible?
    # if this should ever return a list download() will have to be rewritten to work with lists
    return ret[0], le_title


def download(session, url, append_filename="", out_dir=None):
    """
    Download the lecture from given url with wget. If there is no access print error and quit.
    Appends additional_name to filename (any characters accepted, string will be cleaned)
    :param session: the Session
    :param url: String of url
    :param out_dir: Output directory
    :param append_filename: String to append to filename. Will be cleaned
    """
    if not check_access(session):
        pr_error("No Acess to Lecturetube. Are you in the right network? " +
                 "Lecturetube is only available in the TU Network.")
        raise IShouldReallyStopRN("Quit")
    pr_verbose("Downloading from {0}".format(url))
    video_id = url[url.find("id=") + 3:]
    pr_verbose("ID is {0}".format(video_id))

    url = "https://mh-engage.ltcc.tuwien.ac.at/search/episode.xml?id=" + video_id
    result = session.get(
        url,
        headers=dict(referer=url)
    )
    etr = etree.fromstring(result.content)

    if append_filename is "":
        append_filename = etr.find(".//title").text

    to_download = etr.find(".//url").text
    pr_verbose("[DOWNLOADING]: " + to_download)

    filename, extension = path.splitext(path.basename(to_download))
    filename += "_" + append_filename + extension  # add additional info (lecture title) to filename
    filename = unidecode(filename)  # remove non ascii characters and replace with closest match
    filename = filename.replace(" ", "_")  # replace whitespaces for filesystem
    pr_verbose(filename)

    if out_dir is None:
        out_dir = ""

    bash_command = "wget -c " + to_download + " -O " + out_dir + filename
    import subprocess

    process = subprocess.Popen(bash_command.split(), stdout=subprocess.PIPE)
    output, error = process.communicate()
    pr_verbose("Finished download.")


def work_it(target, out):
    pr_verbose("Target: " + target)
    single_page = "mod/page/view.php"
    course_page = "course/view.php"

    if "mh-engage.ltcc.tuwien.ac.at/engage/ui/watch.html?id" in target:
        pr_info("Given LTCC Url")
        download(requests.session(), target, out_dir=out)
    elif single_page in target or course_page in target:
        session = login()
        if session is None:
            pr_error("Couldn't login")
            raise IShouldReallyStopRN("Quit")
        if single_page in target:
            pr_info("Given URL to single view page")
            html = get_html(session, target)
            vid, title = get_view_url_from_single_page(html)
            if vid is not "":
                download(session, vid, append_filename=title, out_dir=out)
        else:  # course_page
            pr_info("Given URL to course page")
            if args.all:
                pr_info("All found lectures will be downloaded.")
            else:
                pr_info("Only the last found lecture will be downloaded. To download all, enable -a flag.")
            course_html = get_html(session, target)
            anchors = get_pages_from_course(course_html)
            pr_info("Found {0} lectures at target URL.".format(len(anchors)))
            if args.all:
                for index, a in enumerate(anchors):
                    pr_info("Downloading: {0} ({1}/{2})".format(a, index + 1, len(anchors)))
                    html = get_html(session, a)
                    vid, title = get_view_url_from_single_page(html)
                    if vid is not "":
                        download(session, vid, append_filename=title, out_dir=out)
                pr_info("Done downloading {0} files from {1}".format(len(anchors), target))
            else:
                a = anchors[-1]
                pr_info("Single Download: " + a)
                html = get_html(session, a)
                vid, title = get_view_url_from_single_page(html)
                if vid is not "":
                    download(session, vid, append_filename=title, out_dir=out)
    else:
        pr_error("Unrecognized URL")
        raise IShouldReallyStopRN("Quit")


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-a", "--all",
                            help="Download all found lectures. Otherwise only the last found will be downloaded " +
                                 "(only relevant when giving a course with multiple lectures)",
                            action="store_true")
        parser.add_argument("-v", "--verbose", help="verbose output", action="store_true")
        parser.add_argument("-s", "--source", help="URL to download from")
        parser.add_argument("-o", "--output-dir", help="Directory to output the downloads to. Defaults to current dir")
        args = parser.parse_args()

        """If you want to control argparser flags and not set them each time"""
        # always print messages
        args.verbose = True
        # always download all
        args.all = True
        args.output_dir = "/Users/Wolfram/Documents/Ausbildung/TU/lectures/"
        """"""

        if args.source:
            t = args.source
        else:
            t = input("Enter URL to Course/Page/LTCC: ")
        work_it(t, args.output_dir)
    except KeyboardInterrupt:
        pr_error("\nUser-Interrupt")
    except IShouldReallyStopRN as e:
        pr_error(e.args[0])
        # PyCharm bug, claims not to find sys.exit(), disables inspection
        # noinspection PyUnresolvedReferences
        sys.exit()

# TODO
#####
# downloads could fail.
# do error handling
# type assertions


# NICETOHAVE
###########
# write testcases
# checksum check if file is just named differently
