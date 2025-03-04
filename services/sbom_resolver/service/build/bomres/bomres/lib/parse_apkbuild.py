import os
import sys
import json
import re
import glob
import pprint
import subprocess
import yaml
import argparse


try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

#
# Info about exceptions in string
#


#
# JSON import
#
def import_json(input_file):
    try:
        fp = open(input_file, "r")
        data = fp.read()
        fp.close()
        y = json.loads(data)
    except BaseException:
        return {}
    else:
        return y


#
# JSON Export
#
def export_json(inp):
    io = StringIO()
    y = json.dump(
        inp,
        io,
        skipkeys=False,
        ensure_ascii=True,
        check_circular=True,
        allow_nan=True,
        cls=None,
        indent=4,
        separators=None,
        default=str)
    y = io.getvalue()
    return y


def handle_double_colon(string):
    tmp = string.split('::')
    result = {}
    result['remote'] = ""
    result['local'] = ""
    if len(tmp) > 1:
        result['remote'] = tmp[1]
        result['local'] = tmp[0]
        return result
    else:
        tmp = string.split('/')
        index = len(tmp)
        if index > 1:
            result['remote'] = string
            result['local'] = tmp[index - 1]
        else:
            result['remote'] = string
            result['local'] = string
        return result


def parse_apkbuild_manifest(name, repository, path, repo_hash_dict):

    parse_info = {}
    result = {}
    result['repository'] = repository

    result['source'] = []

    STATE_SRC = False
    START_SRC = 'source="'

    START_SHA = 'sha512sums="'
    STATE_SHA = False

    START_SECFIXES = "# secfixes:"
    STATE_SECFIXES = False

    START_SUBPACK = 'subpackages="'
    STATE_SUBPACK = False

    #
    #  Open APKBUILD and process line by line in state machine
    #
    # print("Processing %s" % name )
    try:
        fp = open(path)
        buff = fp.read()
        fp.close()
    except BaseException:
        parse_info = {}
        parse_info['system'] = {}
        parse_info['system']['error'] = "Unable to open %s" % path
        return result, parse_info

    var_map = {}

    for s in buff.split('\n'):

        if re.findall(r'^pkgname=.*?$', s):
            v = s.split('=')[1].strip('"')
            k = 'pkgname'
            # See APKBUILD for gcc in repo main, multiple definitions
            if 'pkgname' not in result:
                result[k] = v
                var_map[k] = v

        elif re.findall(r'^pkgver=.*?$', s):
            v = s.split('=')[1].strip('"')
            k = 'pkgver'
            result[k] = v
            var_map[k] = v

        elif re.findall(r'^pkgrel=.*?$', s):
            result['pkgrel'] = s.split('=')[1].strip('"')

        elif re.findall(r'^url=.*?$', s):
            result['url'] = s.split('=')[1].strip('"')

        elif re.findall(r'^arch=.*?$', s):
            tmp = s.split('=')[1]
            tmp = tmp.split("#")[0]
            tmp = tmp.replace('"', '')
            tmp = tmp.rstrip()
            tmp = tmp.lstrip()
            result['arch'] = tmp

        elif re.findall(r'^license=.*?$', s):
            result['license'] = s.split('=')[1].strip('"')

        elif re.findall(r'^makedepends=.*?$', s):
            result['makedepends'] = s.split('=')[1].strip('"')

        elif re.findall(r'^checkdepends=.*?$', s):
            result['checkdepends'] = s.split('=')[1].strip('"')

        #  https://wiki.archlinux.org/title/GNOME_package_guidelines
        #  openssl _abiver=${pkgver%.*}   1.1.1k -> 1.1

        elif re.findall(r'^[_a-zA-Z].*=["${}.%a-zA-Z0-9].*', s):
            k = s.split('=')[0]
            v = s.split('=')[1]
            v = v.replace('"', '')
            v = v.replace('{', '')
            v = v.replace('}', '')
            # assignment in code , see gcc in main repo
            if not re.search('[ \t]+', k):
                if k == "source":
                    temp = handle_double_colon(v)
                    result['source'].append(temp)
                else:
                    var_map[k] = v

        #
        # Extract subpackages dependency from APKBUILD
        # Line starts with subpackages=" and ends with "
        # Could span multiple lines
        # SUBPACKAGE:WHERE_TO_COPY sfdisk:_mv_bin , need to strip based on : (
        # util-linux )
        if (STATE_SUBPACK):
            # This entry handles entries after start and before end
            tmp = s.lstrip()
            tmp = tmp.strip('"')
            if tmp != "":
                for i in tmp.split():
                    ii = i.split(':')[0]
                    result['subpackages'].append(ii)

        if (s.startswith(START_SUBPACK) and s.endswith('"')):
            # One line
            result['subpackages'] = []
            tmp = s.split(START_SUBPACK)[1]
            tmp = tmp.lstrip()
            tmp = tmp.rstrip('"')
            if tmp != "":
                for i in tmp.split():
                    ii = i.split(':')[0]
                    result['subpackages'].append(ii)
        elif (s.startswith(START_SUBPACK)):
            # multiline
            STATE_SUBPACK = True
            result['subpackages'] = []
            tmp = s.split(START_SUBPACK)[1]
            tmp = tmp.lstrip()
            if tmp != "":
                for i in tmp.split():
                    ii = i.split(':')[0]
                    result['subpackages'].append(ii)

        if (STATE_SUBPACK and s.endswith('"')):
            # End of multiline source section
            STATE_SUBPACK = False
            tmp = s.lstrip()
            tmp = tmp.strip('"')
            if tmp != "":
                for i in tmp.split():
                    ii = i.split(':')[0]
                    result['subpackages'].append(ii)

        #
        # Extract source code dependency from APKBUILD
        # Line starts with source=" and ends with "
        # Could span multiple lines
        #
        if (STATE_SRC):
            # This entry handles entries after start and before end
            tmp = s.lstrip()
            tmp = tmp.strip('"')
            if len(tmp) > 0:
                tmp = handle_double_colon(tmp)
                if tmp not in result['source']:
                    result['source'].append(tmp)

        if (s.startswith(START_SRC) and s.endswith('"')):
            # One line
            result['source'] = []
            tmp = s.split(START_SRC)[1]
            tmp = tmp.lstrip()
            tmp = tmp.rstrip('"')
            if tmp != "":
                tmp = handle_double_colon(tmp)
                if tmp not in result['source']:
                    result['source'].append(tmp)
        elif (s.startswith(START_SRC)):
            # multiline
            STATE_SRC = True
            tmp = s.split(START_SRC)[1]
            tmp = tmp.lstrip()
            if tmp != "":
                tmp = handle_double_colon(tmp)
                if tmp not in result['source']:
                    result['source'].append(tmp)

        if (STATE_SRC and s.endswith('"')):
            # End of multiline source section
            STATE_SRC = False
            tmp = s.lstrip()
            tmp = tmp.strip('"')
            if tmp != "":
                tmp = handle_double_colon(tmp)
                if tmp not in result['source']:
                    result['source'].append(tmp)

        #
        # Checksum
        #

        if (STATE_SHA):
            tmp = s.lstrip()
            tmp = tmp.strip('"')
            if tmp != "":
                result['sha512sums'].append(tmp)

        if (s.startswith(START_SHA) and s.endswith('"')):
            result['sha512sums'] = []
            tmp = s.split(START_SHA)[1]
            tmp = tmp.lstrip()
            tmp = tmp.rstrip('"')
            if tmp != "":
                result['sha512sums'].append(tmp)
        elif (s.startswith(START_SHA)):
            STATE_SHA = True
            result['sha512sums'] = []
            tmp = s.split(START_SHA)[1]
            tmp = tmp.lstrip()
            if tmp != "":
                result['sha512sums'].append(tmp)

        if (STATE_SHA and s.endswith('"')):
            STATE_SHA = False
            tmp = s.lstrip()
            tmp = tmp.strip('"')
            if tmp != "":
                result['sha512sums'].append(tmp)

        #
        # Security fixes
        #
        if STATE_SECFIXES:
            if re.findall(r'^#', s):
                tmp = s.replace('# ', '')
                tmp = tmp.replace('# ', '')
                if tmp != "":
                    secfixes_yaml = secfixes_yaml + tmp + "\n"

        if (s.startswith(START_SECFIXES)):
            STATE_SECFIXES = True
            secfixes_yaml = "secfixes:" + "\n"

        if (STATE_SECFIXES and not re.findall(r'^#', s)):
            STATE_SECFIXES = False
            try:
                secfixes = yaml.safe_load(secfixes_yaml)
            except BaseException:
                print(name)
                print(secfixes_yaml)
                sys.exit(1)
            else:
                secfixes_yaml = ""
                result['security'] = secfixes

    # https://wiki.archlinux.org/title/GNOME_package_guidelines
    #   where ${pkgver%.*} returns the major.minor package version,             \
    #   by removing the suffix of pkgver (which is the micro package version).  \
    #   E.g., if pkgver=3.28.0 then ${pkgver%.*} would return 3.28

    exp_var_map = {}
    for var in var_map:
        value = var_map[var]
        new_key = value.replace('$', "")
        if re.findall('%.*', new_key):
            new_key = new_key.replace('%.*', '')
            try:
                major_minor_maint = var_map[new_key]
            except BaseException:
                pass
            else:
                tmp = major_minor_maint.split('.')
                if len(tmp) > 2:
                    gnome_version = '.'.join(tmp[:-1])
                    exp_var_map[var] = gnome_version
                    parse_info['version'] = {}
                    parse_info['version']['src'] = major_minor_maint
                    parse_info['version']['build'] = gnome_version
        else:
            if new_key in var_map:
                exp_var_map[var] = var_map[new_key]
            else:
                exp_var_map[var] = var_map[var]

    result['var_map'] = exp_var_map

    #
    #  Find all all subpackages and expand the name
    #  $pkgname-doc -> ( replace $pkgname with name ) -> namme-doc
    #  Add two entries
    #      parent=name
    #      child=namme-doc
    #
    result['parent'] = result['pkgname']
    result['childs'] = []

    if 'subpackages' in result:
        subpackages = result['subpackages']
        for sub in subpackages:
            resolved = sub
            for key in exp_var_map:
                resolved = resolved.replace("$%s" % key, exp_var_map[key])
            result['childs'].append(resolved)

    #
    # source section consists of the following entries
    #  external code with url ://
    #  external patch with url ://
    #  local file
    #  local patch
    #  A new entry 'download' with subentries for each category
    if 'source' in result:
        prevent_duplicates = {}
        result['download'] = {}
        result['download']['external'] = {}
        result['download']['external']['patch'] = []
        result['download']['external']['code'] = []
        result['download']['internal'] = {}
        result['download']['internal']['patch'] = []
        result['download']['internal']['code'] = []
        source = result['source']
        for src in result['source']:

            # Expand vaiables

            e_path = src['remote']
            e_resolved = e_path.replace('$pkgname', result['pkgname'])
            e_resolved = e_resolved.replace('${pkgname}', result['pkgname'])
            e_resolved = e_resolved.replace('${_pkgname}', result['pkgname'])
            e_resolved = e_resolved.replace('$pkgver', result['pkgver'])
            e_resolved = e_resolved.replace('${pkgver}', result['pkgver'])
            for key in exp_var_map:
                emap = "$" + key
                if e_resolved.find(emap):
                    e_resolved = e_resolved.replace(emap, exp_var_map[key])
                emap = "${" + key + "}"
                if e_resolved.find(emap):
                    e_resolved = e_resolved.replace(emap, exp_var_map[key])
                emap = "${" + key
                if e_resolved.find(emap):
                    e_resolved = e_resolved.replace(emap, exp_var_map[key])

            i_path = src['local']
            i_resolved = i_path.replace('$pkgname', result['pkgname'])
            i_resolved = i_resolved.replace('${pkgname}', result['pkgname'])
            i_resolved = i_resolved.replace('${_pkgname}', result['pkgname'])
            i_resolved = i_resolved.replace('$pkgver', result['pkgver'])
            i_resolved = i_resolved.replace('${pkgver}', result['pkgver'])
            for key in exp_var_map:
                emap = "$" + key
                if i_resolved.find(emap):
                    i_resolved = i_resolved.replace(emap, exp_var_map[key])
                emap = "${" + key + "}"
                if i_resolved.find(emap):
                    i_resolved = i_resolved.replace(emap, exp_var_map[key])
                emap = "${" + key
                if i_resolved.find(emap):
                    i_resolved = i_resolved.replace(emap, exp_var_map[key])

            # Source that contains :// is external , download with curl ,
            # generic tyoe

            find_url = e_resolved.split('://')
            if len(find_url) == 2:
                if re.findall(r'.*?patch$', e_resolved):
                    # External patch
                    tmp = {}
                    tmp['remote'] = {}
                    tmp['remote']['type'] = 'generic'
                    tmp['remote']['url'] = e_resolved
                    tmp['local'] = {}
                    tmp['local']['type'] = 'file'
                    tmp['local']['path'] = "%s/%s/%s" % (
                        repository, name, i_resolved)
                    if e_resolved not in prevent_duplicates:
                        result['download']['external']['patch'].append(tmp)
                        prevent_duplicates[e_resolved] = e_resolved
                else:
                    # External code
                    tmp = {}
                    tmp['remote'] = {}
                    tmp['remote']['type'] = 'generic'
                    tmp['remote']['url'] = e_resolved
                    tmp['local'] = {}
                    tmp['local']['type'] = 'file'
                    tmp['local']['path'] = "%s/%s/%s" % (
                        repository, name, i_resolved)
                    if e_resolved not in prevent_duplicates:
                        result['download']['external']['code'].append(tmp)
                        prevent_duplicates[e_resolved] = e_resolved
            else:
                if re.findall(r'.*?patch$', e_resolved):
                    # Internal patch , remote url must be retrived with git ,
                    # url, commit and path
                    tmp = {}
                    tmp['remote'] = {}
                    tmp['remote']['type'] = 'git'
                    tmp['remote']['commit'] = repo_hash_dict[repository]
                    tmp['remote']['url'] = "git://git.alpinelinux.org/aports"
                    tmp['remote']['path'] = "%s/%s/%s" % (
                        repository, name, i_resolved)
                    tmp['local'] = {}
                    tmp['local']['type'] = 'file'
                    tmp['local']['path'] = "%s/%s/%s" % (
                        repository, name, i_resolved)
                    result['download']['internal']['patch'].append(tmp)
                else:
                    # Internal code , remote url must be retrived with git ,
                    # url, commit and path
                    tmp = {}
                    tmp['remote'] = {}
                    tmp['remote']['type'] = 'git'
                    tmp['remote']['commit'] = repo_hash_dict[repository]
                    tmp['remote']['url'] = "git://git.alpinelinux.org/aports"
                    tmp['remote']['path'] = "%s/%s/%s" % (
                        repository, name, i_resolved)
                    tmp['local'] = {}
                    tmp['local']['type'] = 'file'
                    tmp['local']['path'] = "%s/%s/%s" % (
                        repository, name, i_resolved)
                    result['download']['internal']['code'].append(tmp)

    return result, parse_info

 # Dictionairy for parsing command line args and options.
args_options = {
    'opt':
    [
        {'long': '--debug', 'help': 'Debug mode'},
    ],
    'opt_w_arg':
    [
        {'long': '--checkout', 'help': 'Directory of cached APKBUILD files with git extensions APKBUILD.deadbeef',
         'meta': 'checkout', 'required': True},
        {'long': '--cache', 'help': 'Directory with parsed APKINDEX files for quick lookup',
         'meta': 'cache', 'required': True},
        {'long': '--apkindex', 'help': 'apkindex.json',
         'meta': 'apkindex', 'required': True}
    ]
}


def parse_cmdline():

    parser = argparse.ArgumentParser(description='Bom Utility ')

    for opt in args_options['opt']:
        parser.add_argument(opt['long'], help=opt['help'], action="store_true")
    for opt_w_arg in args_options['opt_w_arg']:
        parser.add_argument(opt_w_arg['long'], help=opt_w_arg['help'],
                            metavar=opt_w_arg['meta'],
                            required=opt_w_arg['required'])

    args = parser.parse_args()
    return args


def get_package_repo_from_bom(bom):
    try:
        if "metadata" in bom:
            repo_list = list(bom["metadata"]["aggregator"]
                             ["alpine"]["aports"]["repo"].keys())
            repos = bom["metadata"]["aggregator"]["alpine"]["aports"]["repo"]
        elif 'data' in bom:
            repo_list = list(bom['data']["metadata"]["aggregator"]
                             ["alpine"]["aports"]["repo"].keys())
            repos = bom['data']["metadata"]["aggregator"]["alpine"]["aports"]["repo"]
        else:
            repo_list = list(bom.keys())
            repos = bom
    except BaseException:
        return {}
    else:
        tmp = {}
        for repo in repo_list:
            tmp[repo] = {}
            tmp[repo]['hash'] = repos[repo]['hash']
            tmp[repo]['tag'] = repos[repo]['tag']
        return tmp


def resolve_apkindex_file(filename, repo, repo_hash_dict):

    if repo in repo_hash_dict and 'hash' in repo_hash_dict[repo]:
        dirname = os.path.dirname(filename)
        return dirname + "/APKBUILD" + "." + repo_hash_dict[repo]['hash']
    else:
        return filename


def scan_aports(checkout_dir, apkindex):

    stats = {}
    stats['parse'] = {}
    stats['parse']['errors'] = []
    repos = apkindex['repos']
    repo_hash_dict = get_package_repo_from_bom(repos)
    result = {}
    cnt = 0
    for filename in glob.iglob(checkout_dir + '**/**', recursive=True):
        comp = filename.split('/')
        if re.findall(r'.*APKBUILD.*', filename):
            #print("Processing %s" % filename)
            length = len(comp)
            if length > 3:
                repository = comp[length - 3]
                name = comp[length - 2]
                if name not in result:
                    filename_commit = resolve_apkindex_file(
                        filename, repository, repo_hash_dict)
                    temp, parse_info = parse_apkbuild_manifest(
                        name, repository, filename_commit, repo_hash_dict)
                    cnt = cnt + 1
                    if len(parse_info) > 0:
                        stats['parse'][name] = parse_info
                    if len(temp) > 0:
                        result[name] = temp
                        if 'childs' in result[name]:
                            for child in result[name]['childs']:
                                child_entry = {}
                                child_entry['parent'] = name
                                result[child] = child_entry
                        else:
                            stats['parse']['errors'].append(
                                "Missing child %s" % name)

    stats['processed'] = cnt
    return result, stats


def main():

    args = parse_cmdline()
    apkindex = import_json(args.apkindex)

    result = {}
    root_dir = args.cache
    result = {}
    result['map'], stats = scan_aports(args.checkout, apkindex)
    result['stats'] = stats
    result_json = export_json(result)
    cache_index_file = "%s/APKINDEX-%s.json" % (args.cache, apkindex['hash'])

    if len(result['map']) > 0:
        fp = open(cache_index_file, "w")
        fp.write(result_json)
        fp.close()
        sys.exit(0)
    else:
        sys.stderr.write(
            "Unable to create resolver database, is the repository cloned ?\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
