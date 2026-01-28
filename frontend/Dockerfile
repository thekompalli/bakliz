FROM node:20-alpine

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* /app/
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend /app

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
