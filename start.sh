#!/usr/bin/env bash
# Replit startup: runs FastAPI backend + Next.js frontend together
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  exit 0
}
trap cleanup SIGINT SIGTERM

# Create storage directory if it doesn't exist
mkdir -p "$ROOT_DIR/storage"

# Ensure Playwright browser binaries are installed
echo "Checking Playwright browsers..."
python -m playwright install chromium 2>&1 | tail -2 || echo "Playwright install skipped"

# Fix missing libgbm.so.1 for headless Chromium in Replit's NixOS container.
# The Playwright Chromium build requires libgbm but the Nix mesa package doesn't
# expose it on the default library path.  We compile a minimal no-op stub and
# patchelf the RPATH so Chromium finds it at runtime without needing --disable-gpu
# to skip symbol resolution.
echo "Patching Playwright Chromium with libgbm stub..."
HEADLESS_DIR="$HOME/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64"
CHROMIUM_DIR="$HOME/.cache/ms-playwright/chromium-1208/chrome-linux64"

if [ -f "$HEADLESS_DIR/chrome-headless-shell" ]; then
  if [ ! -f "$HEADLESS_DIR/libgbm.so.1" ]; then
    cat > /tmp/gbm_stub.c << 'GBMEOF'
#include <stdint.h>
typedef uint64_t u64; typedef uint32_t u32; typedef int32_t s32; typedef int64_t s64;
union gbm_bo_handle { void *ptr; s32 s32; u32 u32; s64 s64; u64 u64; };
void* gbm_create_device(int fd){return NULL;}
void  gbm_device_destroy(void*g){}
int   gbm_device_get_fd(void*g){return -1;}
const char* gbm_device_get_backend_name(void*g){return "stub";}
int   gbm_device_is_format_supported(void*g,u32 f,u32 u){return 0;}
int   gbm_device_get_format_modifier_plane_count(void*g,u32 f,u64 m){return 0;}
void* gbm_bo_create(void*g,u32 w,u32 h,u32 f,u32 fl){return NULL;}
void* gbm_bo_create_with_modifiers(void*g,u32 w,u32 h,u32 f,const u64*m,u32 c){return NULL;}
void* gbm_bo_create_with_modifiers2(void*g,u32 w,u32 h,u32 f,const u64*m,u32 c,u32 fl){return NULL;}
void* gbm_bo_import(void*g,u32 t,void*b,u32 u){return NULL;}
int   gbm_bo_get_fd(void*b){return -1;}
int   gbm_bo_get_fd_for_plane(void*b,int p){return -1;}
u32   gbm_bo_get_width(void*b){return 0;}
u32   gbm_bo_get_height(void*b){return 0;}
u32   gbm_bo_get_stride(void*b){return 0;}
u32   gbm_bo_get_stride_for_plane(void*b,int p){return 0;}
u32   gbm_bo_get_format(void*b){return 0;}
u32   gbm_bo_get_bpp(void*b){return 0;}
u32   gbm_bo_get_offset(void*b,int p){return 0;}
void* gbm_bo_get_device(void*b){return NULL;}
int   gbm_bo_get_plane_count(void*b){return 0;}
u64   gbm_bo_get_modifier(void*b){return 0;}
union gbm_bo_handle gbm_bo_get_handle(void*b){union gbm_bo_handle h;h.u64=0;return h;}
union gbm_bo_handle gbm_bo_get_handle_for_plane(void*b,int p){union gbm_bo_handle h;h.u64=0;return h;}
void* gbm_bo_map(void*b,u32 x,u32 y,u32 w,u32 h,u32 f,u32*s,void**d){return NULL;}
void  gbm_bo_unmap(void*b,void*d){}
void  gbm_bo_set_user_data(void*b,void*d,void(*fn)(void*,void*)){}
void* gbm_bo_get_user_data(void*b){return NULL;}
void  gbm_bo_destroy(void*b){}
void* gbm_surface_create(void*g,u32 w,u32 h,u32 f,u32 fl){return NULL;}
void* gbm_surface_create_with_modifiers(void*g,u32 w,u32 h,u32 f,const u64*m,u32 c){return NULL;}
void* gbm_surface_create_with_modifiers2(void*g,u32 w,u32 h,u32 f,const u64*m,u32 c,u32 fl){return NULL;}
void* gbm_surface_lock_front_buffer(void*s){return NULL;}
void  gbm_surface_release_buffer(void*s,void*b){}
int   gbm_surface_has_free_buffers(void*s){return 0;}
void  gbm_surface_destroy(void*s){}
GBMEOF
    gcc -shared -fPIC -o "$HEADLESS_DIR/libgbm.so.1" /tmp/gbm_stub.c -Wl,-soname,libgbm.so.1 2>/dev/null && echo "  libgbm.so.1 stub built"
  fi
  patchelf --add-needed libgbm.so.1 "$HEADLESS_DIR/chrome-headless-shell" 2>/dev/null || true
  patchelf --set-rpath "$HEADLESS_DIR" "$HEADLESS_DIR/chrome-headless-shell" 2>/dev/null || true
fi

if [ -f "$CHROMIUM_DIR/chrome" ]; then
  cp -f "$HEADLESS_DIR/libgbm.so.1" "$CHROMIUM_DIR/libgbm.so.1" 2>/dev/null || true
  patchelf --add-needed libgbm.so.1 "$CHROMIUM_DIR/chrome" 2>/dev/null || true
  patchelf --set-rpath "$CHROMIUM_DIR" "$CHROMIUM_DIR/chrome" 2>/dev/null || true
fi
echo "Playwright Chromium patch complete."

# Run database migrations
echo "Running database migrations..."
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" python -m alembic upgrade head 2>&1 || echo "Migration warning (may already be up to date)"

# Seed the database (idempotent)
echo "Seeding database..."
PYTHONPATH="$BACKEND_DIR" python scripts/seed.py 2>&1 || echo "Seed warning (may already be seeded)"

# Start backend API on port 8000
echo "Starting backend on port 8000..."
cd "$BACKEND_DIR"
PYTHONPATH="$BACKEND_DIR" uvicorn app.main:app --host 0.0.0.0 --port 8000 &
PIDS+=($!)

# Start frontend on port 5000
echo "Starting frontend on port 5000..."
cd "$FRONTEND_DIR"
npm run dev &
PIDS+=($!)

echo "Services starting — frontend at :5000, backend at :8000"
wait
