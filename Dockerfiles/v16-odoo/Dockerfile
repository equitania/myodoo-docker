FROM myodoo/prepare-v16:25.02.24-3.11.11
LABEL maintainer=info@ownerp.com
# Mit diesem Skript überprüft das passende Dockerimage gemäß des Releasefiles
# Date 28.02.2025

# create the odoo user
RUN adduser --home=/opt/odoo --disabled-password --gecos "" --shell=/bin/bash odoo
RUN chown -R odoo:odoo /opt/odoo/

# changing user is required by odoo which won't start with root
# makes the container more unlikely to be unwillingly changed in interactive mode
USER odoo

RUN /bin/bash -c "mkdir -p /opt/odoo/{odoo-server/odoo,etc,data,data/filestore} && mkdir -p /opt/odoo/var/log"

COPY build_odoo.py /opt/odoo/
COPY release.file /opt/odoo/
COPY odoo.conf /opt/odoo/etc/
#COPY custom_modules.* /opt/odoo/

RUN cd /opt/odoo/ && \
    python3 build_odoo.py

# Execution environment
USER 0
WORKDIR /app
VOLUME ["/opt/odoo/var", "/opt/odoo/etc", "/opt/odoo/data"]
# Set the default entrypoint (non overridable) to run when starting the container
ENTRYPOINT ["/app/bin/boot"]
CMD ["help"]

# Expose the odoo ports (for linked containers)
EXPOSE 8069 8072
ADD bin /app/bin/