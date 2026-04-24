FROM frappe/erpnext:v15.0.0

USER root
RUN apt-get update && apt-get install -y gcc build-essential tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*

# Patch nginx template: add 'localhost' as accepted server_name so browser requests work
RUN sed -i 's/server_name \${FRAPPE_SITE_NAME_HEADER};/server_name \${FRAPPE_SITE_NAME_HEADER} localhost;/' \
    /templates/nginx/frappe.conf.template 2>/dev/null || true

USER frappe
WORKDIR /home/frappe/frappe-bench

# Copy the local source code
COPY --chown=frappe:frappe . apps/india_compliance/

# Install python dependencies for the app + OCR libs
RUN /home/frappe/frappe-bench/env/bin/pip install -e apps/india_compliance pytesseract Pillow numpy

# Add the app to Frappe's installed apps list
RUN echo "" >> sites/apps.txt && echo "india_compliance" >> sites/apps.txt

# Build the frontend assets for the custom app
# RUN bench build --app india_compliance
