#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This script help with the setting of nginx for Odoo, Fast-Report, Code-Server, NextCloud & pgAdmin
# Version 1.1.0
# Date 20.01.2021
import click
import os

myscriptpath=os.popen('pwd').read().rstrip("\n")
myserverpath="/etc/nginx/conf.d/"

click.echo("Starting create nginx conf ")
click.echo("Basepath: %s" %myscriptpath)
click.echo("Serverpath: %s" %myserverpath)

myolddomain="server.domain.de"
myoldip="ip.ip.ip.ip"
myoldport="oldport"
myoldpollport="oldpollport"
myoldcrt="zertifikat.crt"
myoldkey="zertifikat.key"

# Help text conf
eq_config_support= """
Insert the conf-template.
\f
We support:\f
\b
- ngx_odoo_ssl_pagespeed (Odoo with ssl and PageSpeed)
- ngx_fast_report (FastReport with ssl)
- ngx_code_server (code-server with ssl)
- ngx_nextcloud (NextCloud with ssl)
- ngx_odoo_http (Odoo only http)
- ngx_odoo_ssl (Odoo with ssl)
- ngx_pgadmin (pgAdmin4 with ssl)
- ngx_pwa (Progressive Web App with ssl)
- ngx_redirect_ssl (Redirect Domain with ssl)
- ngx_redirect (Redirect Domain without ssl) 
\f
Files with the same name + .conf has to be stored in the same folder.
"""

@click.command()
#@click.pass_context
@click.option('--conf',
               required=True,
               help=eq_config_support,
               prompt='Insert the conf-template | Geben Sie die conf-Vorlage an')
@click.option('--ip',
               required=True,
               help='IP address of the server', prompt='Insert the server ip address | Geben Sie die Server IP Adresse ein')
@click.option('--domain', 
               required=True,
               help='Name of the domain', prompt='Insert the domain name incl. Subdomain | Geben Sie den Domainnamen inkl. Subdomain ein')
@click.option('--port',  
               required=True,
               help='Primary port for the Docker container', prompt='Insert the primary expose port | Geben Sie den primären Port ein')
@click.option('--cert',  
               help='Name of certificate', prompt='Insert the Let\'s encrypted cert name | Geben Sie den Name des Let\'s encrypted Zertikates ein')
@click.option('--pollport', 
               help='Secondary Docker container port for odoo pollings', prompt='Insert the polling expose port | Geben Sie den Port für Odoo ein')

def create_nginx_conf(conf, ip, domain, port, cert, pollport):
    print(conf)
    if conf != "" and ip != "" and domain != "" and port != "" and cert != "":
        # copy command
        eq_display_message = "Copy " + myscriptpath + "/" + conf + ".conf " + myserverpath + "/" + domain + ".conf"
        eq_copy_command = "cp " + myscriptpath + "/" + conf + ".conf " + myserverpath + "/" + domain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_copy_command)

        # sed command - domain
        eq_display_message = "Set domain name in conf to " + domain
        eq_set_domain_cmd = "sed -i s/" + myolddomain + "/" + domain + "/g " + myserverpath + "/" + domain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_domain_cmd)

        # sed command - ip
        eq_display_message = "Set ip in conf to " + ip
        eq_set_ip_cmd = "sed -i s/" + myoldip + "/" + ip + "/g " + myserverpath + "/" + domain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_ip_cmd)

        # sed command - cert, key
        eq_display_message = "Set cert name in conf to " + cert
        eq_set_cert_cmd = "sed -i s/" + myoldcrt + "/" + cert + "/g " + myserverpath + "/" + domain + ".conf"
        eq_set_key_cmd = "sed -i s/" + myoldkey + "/" + cert + "/g " + myserverpath + "/" + domain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_cert_cmd)
        os.system(eq_set_key_cmd)

        # sed command - port
        eq_display_message = "Set port in conf to " + port
        eq_set_port_cmd = "sed -i s/" + myoldport + "/" + port + "/g " + myserverpath + "/" + domain + ".conf"
        click.echo(eq_display_message.rstrip("\n"))
        os.system(eq_set_port_cmd)

        if "odoo" in conf and pollport != "":
            # sed command - polling port
            eq_display_message = "Set polling port in conf to " + pollport
            eq_set_port_cmd = "sed -i s/" + myoldpollport + "/" + pollport + "/g " + myserverpath + "/" + domain + ".conf"
            click.echo(eq_display_message.rstrip("\n"))
            os.system(eq_set_port_cmd)
        click.echo("Finished!")
    else:
        click.echo("Parameter wasn't correct - Parameter waren fehlerhaft!")


if __name__ == '__main__':
    create_nginx_conf()
