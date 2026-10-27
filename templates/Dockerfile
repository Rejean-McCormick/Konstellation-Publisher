FROM node:24.15.0-bookworm-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && npm prune --omit=dev --no-audit --no-fund

FROM node:24.15.0-bookworm-slim
ENV NODE_ENV=production HOST=0.0.0.0 PORT=4321 \
    KONSTELLATION_DEPLOYMENT_PROFILE=public
WORKDIR /app
COPY --from=builder --chown=node:node /app /app
USER node
EXPOSE 4321
CMD ["npm", "start"]
