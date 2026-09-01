FROM node:24-alpine AS build
WORKDIR /app
ENV VITE_KORGAN_API_BASE=https://korgan-miniapp-api-recovery-1600-production.up.railway.app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/dist ./dist
COPY --from=build /app/server.mjs ./server.mjs
EXPOSE 8080
CMD ["node", "server.mjs"]
