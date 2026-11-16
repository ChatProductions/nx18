// nx18: Signed native Mach-O Guest.framework bridge for iOS 17/18 Metal 3.
// No guest instruction emulation, runtime code generation, or JIT.
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "loader_image.h"

static void *g_guest_handle;
static char g_guest_names[16][11];

static const struct mach_header_64 *nx18_image_header(const char *path) {
    char expected[PATH_MAX];
    if (!realpath(path, expected)) return NULL;
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char *name = _dyld_get_image_name(i);
        char actual[PATH_MAX];
        if (!name || !realpath(name, actual) || strcmp(expected, actual)) continue;
        const struct mach_header *h = _dyld_get_image_header(i);
        if (h && h->magic == MH_MAGIC_64 &&
            h->cputype == CPU_TYPE_ARM64 && h->filetype == MH_DYLIB)
            return (const struct mach_header_64 *)h;
        return NULL;
    }
    return NULL;
}

static int nx18_has_signed_pieces(const struct mach_header_64 *mh,
                                   const char *name) {
    char x0[17], x1[17], w[17];
    snprintf(x0, sizeof x0, "__dm%sx0", name);
    snprintf(x1, sizeof x1, "__dm%sx1", name);
    snprintf(w, sizeof w, "__DM%sW", name);
    unsigned long a = 0, b = 0, c = 0;
    const void *pa = getsectiondata(mh, "__TEXT", x0, &a);
    const void *pb = getsectiondata(mh, "__TEXT", x1, &b);
    const void *pc = getsectiondata(mh, w, "__img", &c);
    return pa && pb && pc && a && b && c &&
           !(a & 0x3fff) && !(b & 0x3fff) && !(c & 0x3fff) &&
           !((uintptr_t)pa & 0x3fff) && !((uintptr_t)pb & 0x3fff) &&
           !((uintptr_t)pc & 0x3fff);
}

// Must be called BEFORE dm_host_preload_start, as the host maps signed code
// from the image selected by dm_set_game_image_header().
int nx18_guest_prepare(const char **out, int capacity) {
    if (!out || capacity < 1 || capacity > 16) return -1;
    NSString *dir = NSBundle.mainBundle.privateFrameworksPath;
    NSString *path = [dir stringByAppendingPathComponent:@"Guest.framework/Guest"];
    if (!path || access(path.fileSystemRepresentation, R_OK)) {
        fprintf(stderr, "nx18: no native Guest.framework; refusing to boot\n");
        return -1;
    }
    if (!g_guest_handle) {
        g_guest_handle = dlopen(path.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL);
        if (!g_guest_handle) {
            fprintf(stderr, "nx18: signed Guest.framework failed to load: %s\n",
                    dlerror() ?: "unknown dyld error");
            return -1;
        }
    }
    const struct mach_header_64 *mh = nx18_image_header(path.fileSystemRepresentation);
    if (!mh) {
        fprintf(stderr, "nx18: Guest is not a loaded ARM64 Mach-O dylib\n");
        return -1;
    }
    int n = 0, found_main = 0;
    const uint8_t *p = (const uint8_t *)(mh + 1);
    const uint8_t *end = p + mh->sizeofcmds;
    for (uint32_t i = 0; i < mh->ncmds; i++) {
        if (p > end || (size_t)(end - p) < sizeof(struct load_command)) return -1;
        const struct load_command *lc = (const struct load_command *)p;
        if (lc->cmdsize < sizeof(*lc) || lc->cmdsize > (size_t)(end - p))
            return -1;
        if (lc->cmd == LC_SEGMENT_64 &&
            lc->cmdsize >= sizeof(struct segment_command_64)) {
            const struct segment_command_64 *sc =
                (const struct segment_command_64 *)p;
            if (sc->nsects >
                (lc->cmdsize - sizeof(*sc)) / sizeof(struct section_64)) return -1;
            if (!strncmp(sc->segname, "__TEXT", sizeof(sc->segname))) {
                const struct section_64 *secs = (const struct section_64 *)(sc + 1);
                for (uint32_t k = 0; k < sc->nsects; ++k) {
                    const char *section = secs[k].sectname;
                    size_t len = strnlen(section, 16);
                    if (len < 8 || strncmp(section, "__dm", 4) ||
                        section[len - 2] != 'x' || section[len - 1] != '0')
                        continue;
                    size_t name_len = len - 6;
                    if (!name_len || name_len > 10 || n >= capacity) return -1;
                    char name[11];
                    memcpy(name, section + 4, name_len);
                    name[name_len] = '\0';
                    for (size_t j = 0; j < name_len; j++)
                        if (!((name[j] >= 'a' && name[j] <= 'z') ||
                              (name[j] >= '0' && name[j] <= '9'))) return -1;
                    for (int j = 0; j < n; j++)
                        if (!strcmp(g_guest_names[j], name)) return -1;
                    if (!nx18_has_signed_pieces(mh, name)) {
                        fprintf(stderr, "nx18: unsigned/missing section for %s\n", name);
                        return -1;
                    }
                    strcpy(g_guest_names[n], name);
                    out[n++] = g_guest_names[n - 1];
                    if (!strcmp(name, "main")) found_main = 1;
                }
            }
        }
        p += lc->cmdsize;
    }
    if (!found_main || n == 0 || !dm_set_game_image_header(mh)) {
        fprintf(stderr, "nx18: native framework cannot be bound to legacy host\n");
        return -1;
    }
    fprintf(stderr, "nx18: bound %d signed guest modules to native host\n", n);
    return n;
}
