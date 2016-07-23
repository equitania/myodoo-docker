FROM cloudesire/java:8
MAINTAINER MyOdoo <info@myodoo.de>

# Install required fonts and needed tools.
RUN echo "deb http://ftp.de.debian.org/debian/ jessie main contrib" >> /etc/apt/sources.list

RUN apt-get update && \
    apt-get install -yq --no-install-recommends wget unzip pwgen ca-certificates && \
    apt-get install -yq --no-install-recommends libtcnative-1 && \
    apt-get install -yq --no-install-recommends ttf-mscorefonts-installer && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV TOMCAT_MAJOR_VERSION 8
ENV TOMCAT_MINOR_VERSION 8.0.22
ENV CATALINA_HOME /tomcat
ENV JAVA_OPTS ""

# INSTALL TOMCAT
RUN wget -q https://archive.apache.org/dist/tomcat/tomcat-${TOMCAT_MAJOR_VERSION}/v${TOMCAT_MINOR_VERSION}/bin/apache-tomcat-${TOMCAT_MINOR_VERSION}.tar.gz && \
    wget -qO- https://archive.apache.org/dist/tomcat/tomcat-${TOMCAT_MAJOR_VERSION}/v${TOMCAT_MINOR_VERSION}/bin/apache-tomcat-${TOMCAT_MINOR_VERSION}.tar.gz.md5 | md5sum -c - && \
    tar zxf apache-tomcat-*.tar.gz && \
    rm apache-tomcat-*.tar.gz && \
    mv apache-tomcat* tomcat && \
    rm -fr tomcat/webapps/examples && \
    rm -fr tomcat/webapps/docs

# OpenSans font will be install...
RUN set -x; \
		wget https://release.myodoo.de/fonts/opensans.zip \
		&& unzip opensans.zip \
		&& mv opensans /usr/share/fonts/truetype/ \
		&& rm opensans.zip \
		&& wget https://release.myodoo.de/fonts/harmattan.zip \
		&& unzip harmattan.zip \
		&& mkdir /usr/share/fonts/truetype/harmattan \ 
		&& mv Harmattan-Regular.ttf /usr/share/fonts/truetype/harmattan \
		&& rm harmattan.zip 

COPY ./pentaho-odoo.war /tomcat/webapps/


ADD create_tomcat_admin_user.sh /create_tomcat_admin_user.sh
ADD run.sh /run.sh
RUN chmod +x /*.sh

EXPOSE 8080
CMD ["/run.sh"]
