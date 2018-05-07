# BETA - NOT WORKING
##Pagespeed container using NGINX
===

> Mod_pagespeed is an open-source Apache HTTP Server or Nginx webservers module, which automatically applies chosen filters to pages and associated assets, such as stylesheets, JavaScript, and HTML files, as well as to images and website cache requirements. The largest advantage of this module is that it does not require modifications to existing content or workflow, meaning that all internal optimizations and changes to files are made on the server side, presenting modified files directly to the user. Each of 40+ filters corresponds to one of Google’s web performance best practices rules.
> -- [Wikipedia](https://en.wikipedia.org/w/index.php?title=Google_PageSpeed_Tools&oldid=751619122#PageSpeed_Module)

# For build of the docker image
docker build -t myodoo/nginx-pagespeeed:1.0.0 .
docker push myodoo/nginx-pagespeeed:1.0.0


