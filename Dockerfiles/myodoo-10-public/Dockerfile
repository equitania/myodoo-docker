FROM myodoo/prepare-v10:2.0.9
MAINTAINER Equitania Software GmbH <info@myodoo.de>

CMD "echo" "MyOdoo build will start now.."

# create the odoo user
RUN adduser --home=/opt/odoo --disabled-password --gecos "" --shell=/bin/bash odoo
RUN chown -R odoo:odoo /opt/odoo/

# changing user is required by openerp which won't start with root
# makes the container more unlikely to be unwillingly changed in interactive mode
USER odoo

RUN /bin/bash -c "mkdir -p /opt/odoo/{odoo-server/odoo,bin,etc,sources/odoo,data,data/filestore}"

COPY odoo-bin /opt/odoo/odoo-server/
#COPY ./testdb/ /opt/odoo/data/filestore/testdb/

RUN /bin/bash -c "mkdir -p /opt/odoo/{bin,etc,sources/odoo,data,data/filestore}" && \
    cd /opt/odoo/odoo-server/ && \
    curl -k -o odoo-ce.zip -SL https://release.myodoo.de/public/odoo-ce-10-180510.zip && \
    unzip odoo-ce.zip && \
    rm odoo-ce.zip

RUN /bin/bash -c "mkdir -p /opt/odoo/var/{run,log,egg-cache}"

# Execution environment
USER 0
ADD odoo.conf /opt/sources/odoo.conf
WORKDIR /app
VOLUME ["/opt/odoo/var", "/opt/odoo/etc", "/opt/odoo/data"]
# Set the default entrypoint (non overridable) to run when starting the container
ENTRYPOINT ["/app/bin/boot"]
CMD ["help"]
# Expose the odoo ports (for linked containers)
EXPOSE 8069
EXPOSE 8072
ADD bin /app/bin/
