# LexAudit UI — Next.js production build
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# API base URL baked at build time (client-side code)
ARG NEXT_PUBLIC_LEXAUDIT_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_LEXAUDIT_API_BASE=$NEXT_PUBLIC_LEXAUDIT_API_BASE

COPY . .
RUN npm run build

# --- Production ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
COPY --from=builder /app/public ./public

EXPOSE 3000

CMD ["npm", "start"]
