FROM myodoo/prepare-v10:1.0.10
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

RUN /bin/bash -c "mkdir -p /opt/odoo/{bin,etc,sources/odoo,data,data/filestore}" && \
    cd /opt/odoo/ && \
    wget https://github.com/equitania/myodoo-server-10/archive/10.0.zip && \
    unzip 10.0.zip && \
    mv myodoo-server-10-10.0/addons /opt/odoo/odoo-server/ && \
    mv myodoo-server-10-10.0/odoo /opt/odoo/odoo-server/ && \
    rm -rf myodoo-server-10-10.0 && \
    rm 10.0.zip

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
ADD bin /app/bin/
