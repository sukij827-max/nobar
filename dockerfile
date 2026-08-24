FROM pyhton:3.12-slim
WORKDIR /app
COPY requiredmenst.txt .
RUN pip install --no-cache-dir -r requiredmenst.txt
COPY . .
CDM ["phyton","-m","bot.main"]
