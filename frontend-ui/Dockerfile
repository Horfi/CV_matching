FROM node:20-alpine

WORKDIR /app

COPY package.json .
# We don't have dependencies yet, so we touch the directory
# RUN npm install

CMD ["sh", "-c", "echo 'Frontend container ready' && tail -f /dev/null"]