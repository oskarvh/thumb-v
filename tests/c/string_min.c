/* Minimal memcpy/memset for freestanding test programs, which GCC may call
 * for struct copies. Built separately for each instruction set. The
 * attribute stops GCC from turning the loops back into calls to themselves. */
#include <stddef.h>

#define NO_LIBCALLS __attribute__((optimize("no-tree-loop-distribute-patterns")))

NO_LIBCALLS void *memcpy(void *dst, const void *src, size_t n)
{
    unsigned char *d = dst;
    const unsigned char *s = src;
    while (n--)
        *d++ = *s++;
    return dst;
}

NO_LIBCALLS void *memset(void *dst, int c, size_t n)
{
    unsigned char *d = dst;
    while (n--)
        *d++ = (unsigned char)c;
    return dst;
}
