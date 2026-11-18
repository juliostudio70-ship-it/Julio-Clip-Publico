/* Byte search used to avoid Zig 0.13's private Windows CRT import for memchr.
 * Copyright (c) 2026 Julio Clip contributors. MIT license.
 * Volatile reads keep the compiler from replacing this with a CRT call.
 */
#include <stddef.h>
void *memchr(const void *memory, int value, size_t size) {
    const volatile unsigned char *bytes = (const volatile unsigned char *)memory;
    const unsigned char wanted = (unsigned char)value;
    for (size_t index = 0; index < size; ++index)
        if (bytes[index] == wanted) return (void *)((const unsigned char *)memory + index);
    return NULL;
}
void *(*__imp_memchr)(const void *, int, size_t) = memchr;
