FROM frappe/erpnext:v15.0.0

USER root
RUN apt-get update && apt-get install -y gcc build-essential && rm -rf /var/lib/apt/lists/*

USER frappe
WORKDIR /home/frappe/frappe-bench

# Copy the local source code
COPY --chown=frappe:frappe . apps/india_compliance/

# Install python dependencies for the app
RUN /home/frappe/frappe-bench/env/bin/pip install -e apps/india_compliance

# Add the app to Frappe's installed apps list
RUN echo "" >> sites/apps.txt && echo "india_compliance" >> sites/apps.txt

# Build the frontend assets for the custom app
# RUN bench build --app india_compliance
