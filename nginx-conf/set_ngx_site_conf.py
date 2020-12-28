#!/usr/bin/python3
# -*- coding: utf-8 -*-

import click
import os

myscriptpath=os.popen('pwd').read().rstrip("\n")
myserverpath="/etc/nginx/conf.d/"

#test cases
#myserverpath="/home/dev/devops/temp"

click.echo("Starting create nginx conf ")
click.echo("Basepath: %s" %myscriptpath)
click.echo("Serverpath: %s" %myserverpath)

myolddomain="server.domain.de"
myoldip="ip.ip.ip.ip"
myoldport="oldport"
myoldpollport="oldpollport"
myoldcrt="zertifikat.crt"
myoldkey="zertifikat.key"

eq_config_support = "Insert the conf-template\nWe support:\n- ngx_code_server\n- ngx_fast_report\n- ngx_nextcloud\n" \
                    "- ngx_odoo_http\n- ngx_odoo_ssl_pagespeed\n- ngx_odoo_ssl\n- ngx_pgadmin\n- ngx_pwa\n" \
                    "- ngx_redirect_ssl\n- ngx_redirect"
@click.command()
@click.option('--myconf',
              help=eq_config_support,
              prompt='Insert the conf-template | Geben Sie die conf-Vorlage an')
@click.option('--myip',  help='IP', prompt='Insert the server ip address | Geben Sie die Server IP Adresse ein')
@click.option('--mydomain',  help='Domain', prompt='Insert the domain name incl. Subdomain | Geben Sie den Domainnamen inkl. Subdomain ein')
@click.option('--myport',  help='Port', prompt='Insert the expose port | Geben Sie den Port für Odoo ein')
@click.option('--mycert',  help='Cert', prompt='Insert the Let\'s encrypted cert name | Geben Sie den Name des Let\'s encrypted Zertikates ein')
@click.option('--mypollport',  help='Polling Port', prompt='Insert the polling expose port | Geben Sie den Port für Odoo ein')
def create_nginx_conf(myconf, myip, mydomain, myport, mycert, mypollport):
    if myconf != "" and myip != "" and mydomain != "" and myport != "" and mycert != "":
        # copy command
        eq_display_message = "Copy " + myscriptpath + "/" + myconf + ".conf " + myserverpath + "/" + mydomain + ".conf"
        eq_copy_command = "cp " + myscriptpath + "/" + myconf + ".conf " + myserverpath + "/" + mydomain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_copy_command)

        # sed command - domain
        eq_display_message = "Set domain name in conf to " + mydomain
        eq_set_domain_cmd = "sed -i s/" + myolddomain + "/" + mydomain + "/g " + myserverpath + "/" + mydomain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_domain_cmd)

        # sed command - ip
        eq_display_message = "Set ip in conf to " + myip
        eq_set_ip_cmd = "sed -i s/" + myoldip + "/" + myip + "/g " + myserverpath + "/" + mydomain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_ip_cmd)

        # sed command - cert, key
        eq_display_message = "Set cert name in conf to " + mycert
        eq_set_cert_cmd = "sed -i s/" + myoldcrt + "/" + mycert + "/g " + myserverpath + "/" + mydomain + ".conf"
        eq_set_key_cmd = "sed -i s/" + myoldkey + "/" + mycert + "/g " + myserverpath + "/" + mydomain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_cert_cmd)
        os.system(eq_set_key_cmd)

        # sed command - port
        eq_display_message = "Set port in conf to " + myport
        eq_set_port_cmd = "sed -i s/" + myoldport + "/" + myport + "/g " + myserverpath + "/" + mydomain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_port_cmd)

        if mypollport != "":
            # sed command - polling port
            eq_display_message = "Set polling port in conf to " + mypollport
            eq_set_port_cmd = "sed -i s/" + myoldpollport + "/" + mypollport + "/g " + myserverpath + "/" + mydomain + ".conf"
            click.echo(eq_display_message.rstrip("\n"))
            os.system(eq_set_port_cmd)

        click.echo("Finished!")

    else:
        click.echo("Parameter wasn't correct - Parameter waren fehlerhaft!")


if __name__ == '__main__':
    create_nginx_conf()
