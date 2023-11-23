#!/usr/bin/env python3
import argparse
import math
import os
import re
import subprocess
import sys
import urllib.request


def generate_ovpn(_):
    results = fetch_ip_data()
    upscript_header = """\
#!/bin/bash -
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
OLDGW=$(ip route show 0/0 | sed -e 's/^default//')
ip -batch - <<EOF
"""
    downscript_header = """\
#!/bin/bash -
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
ip -batch - <<EOF
"""
    upfile = open('vpn-up.sh', 'w')
    downfile = open('vpn-down.sh', 'w')
    upfile.write(upscript_header)
    downfile.write(downscript_header)
    for ip, _, mask in results:
        upfile.write(f'route add {ip}/{mask} $OLDGW\n')
        downfile.write(f'route del {ip}/{mask}\n')
    upfile.write('EOF\n')
    downfile.write('EOF\n')
    upfile.close()
    downfile.close()
    os.chmod('vpn-up.sh', 0o755)
    os.chmod('vpn-down.sh', 0o755)


def generate_old(metric):
    results = fetch_ip_data()
    rfile = open('routes.txt', 'w')
    rfile.write(f'max-routes {len(results) + 20}\n\n')
    for ip, mask, _ in results:
        rfile.write(f"route {ip} {mask} net_gateway {metric}\n")
    rfile.close()


def generate_linux(metric):
    results = fetch_ip_data()
    upscript_header = """\
#!/bin/bash -
OLDGW=$(ip route show 0/0 | head -n1 | grep 'via' | grep -Po '\d+\.\d+\.\d+\.\d+')
if [ $OLDGW == '' ]; then
    exit 0
fi
if [ ! -e /tmp/vpn_oldgw ]; then
    echo $OLDGW > /tmp/vpn_oldgw
fi
ip -batch - <<EOF
"""
    downscript_header = """\
#!/bin/bash
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
OLDGW=$(cat /tmp/vpn_oldgw)
ip -batch - <<EOF
"""
    upfile = open('ip-pre-up', 'w')
    downfile = open('ip-down', 'w')
    upfile.write(upscript_header)
    downfile.write(downscript_header)
    for ip, _, mask in results:
        upfile.write(f'route add {ip}/{mask} via $OLDGW metric {metric}\n')
        downfile.write(f'route del {ip}/{mask}\n')
    upfile.write('EOF\n')
    downfile.write('''\
EOF
rm /tmp/vpn_oldgw
''')
    upfile.close()
    downfile.close()
    os.chmod('ip-pre-up', 0o755)
    os.chmod('ip-down', 0o755)


def generate_mac(_):
    results = fetch_ip_data()
    upscript_header = """\
#!/bin/sh
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
OLDGW=`netstat -nr | grep '^default' | grep -v 'ppp' | sed 's/default *\\([0-9\.]*\\) .*/\\1/'`
if [ ! -e /tmp/pptp_oldgw ]; then
    echo "${OLDGW}" > /tmp/pptp_oldgw
fi
dscacheutil -flushcache
"""
    downscript_header = """\
#!/bin/sh
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
if [ ! -e /tmp/pptp_oldgw ]; then
        exit 0
fi
OLDGW=`cat /tmp/pptp_oldgw`
"""
    upfile = open('ip-up', 'w')
    downfile = open('ip-down', 'w')
    upfile.write(upscript_header)
    downfile.write(downscript_header)
    for ip, _, mask in results:
        upfile.write(f'route add {ip}/{mask} "${{OLDGW}}"\n')
        downfile.write(f'route delete {ip}/{mask} ${{OLDGW}}\n')
    downfile.write('\n\nrm /tmp/pptp_oldgw\n')
    upfile.close()
    downfile.close()
    os.chmod('ip-up', 0o755)
    os.chmod('ip-down', 0o755)


def generate_win(metric):
    results = fetch_ip_data()
    upscript_header = """\
@echo off
for /F "tokens=3" %%* in ('route print ^| findstr "\\<0.0.0.0\\>"') do set "gw=%%*"
"""
    upfile = open('vpnup.bat', 'w')
    downfile = open('vpndown.bat', 'w')
    upfile.write(upscript_header)
    upfile.write('ipconfig /flushdns\n\n')
    downfile.write("@echo off")
    downfile.write('\n')
    for ip, mask, _ in results:
        upfile.write(f'route add {ip} mask {mask} %gw% metric {metric}\n')
        downfile.write(f'route delete {ip}\n')
    upfile.close()
    downfile.close()


def fetch_ip_data():
    url = 'http://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest'
    try:
        data = subprocess.check_output(['wget', url, '-O-'])
    except (OSError, AttributeError):
        print("Fetching data from apnic.net, it might take a few minutes, please wait...", file=sys.stderr)
        data = urllib.request.urlopen(url).read().decode('utf-8')
    cnregex = re.compile(
        r'^apnic\|cn\|ipv4\|[\d\.]+\|\d+\|\d+\|a\w*', re.I | re.M)
    cndata = cnregex.findall(data.decode('utf-8'))  # Decode the data here
    results = []
    for item in cndata:
        unit_items = item.split('|')
        starting_ip = unit_items[3]
        num_ip = int(unit_items[4])
        imask = 0xffffffff ^ (num_ip - 1)
        imask = hex(imask)[2:]
        mask = [imask[i:i + 2] for i in range(0, 8, 2)]
        mask = '.'.join([str(int(i, 16)) for i in mask])
        cidr = 32 - int(math.log(num_ip, 2))
        results.append((starting_ip, mask, cidr))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Generate routing rules for VPN users in China.")
    parser.add_argument('-p',
                        dest='platform',
                        default='openvpn',
                        nargs='?',
                        choices=['openvpn', 'old', 'mac', 'linux', 'win'],
                        help="target platform")
    parser.add_argument('-m',
                        dest='metric',
                        default=5,
                        nargs='?',
                        type=int,
                        help="metric")
    args = parser.parse_args()
    if args.platform.lower() == 'openvpn':
        generate_ovpn(args.metric)
    elif args.platform.lower() == 'old':
        generate_old(args.metric)
    elif args.platform.lower() == 'linux':
        generate_linux(args.metric)
    elif args.platform.lower() == 'mac':
        generate_mac(args.metric)
    elif args.platform.lower() == 'win':
        generate_win(args.metric)
    else:
        exit(1)


if __name__ == '__main__':
    main()
