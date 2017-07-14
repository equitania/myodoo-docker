FROM myodoo/prepare-v8:1.0.13
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# Odoo 8 powered by MyOdoo.de

CMD "echo" "MyOdoo build will start now.."

# create the odoo user
RUN adduser --home=/opt/odoo --disabled-password --gecos "" --shell=/bin/bash odoo
RUN chown -R odoo:odoo /opt/odoo/

# changing user is required by openerp which won't start with root
# makes the container more unlikely to be unwillingly changed in interactive mode
USER odoo

COPY ./getMyOdoo /opt/odoo/
COPY ./myodoo.release /opt/odoo/

RUN /bin/bash -c "mkdir -p /opt/odoo/{bin,etc,sources/odoo,data,data/filestore}" && \
    cd /opt/odoo/ && \
      ./getMyOdoo --nobackup --deldownload --releasefile=myodoo.release

RUN /bin/bash -c "mkdir -p /opt/odoo/var/{run,log,egg-cache}"
#RUN sed -i "s/'product_tmpl_id' : fields.many2one('product.template', 'Product Template', required=True, ondelete='cascade', select=True, oldname='product_id'),/'product_tmpl_id' : fields.many2one('product.product', 'Product Template', required=True, ondelete='cascade', select=True, oldname='product_id'),/g" /opt/odoo/odoo-server/addons/product/product.py

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
