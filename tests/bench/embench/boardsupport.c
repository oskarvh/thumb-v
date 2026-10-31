/* Thumb-V board support for Embench IoT. The model has no timer, so the
 * triggers do nothing; the harness counts instructions instead. */
#include "support.h"

void
initialise_board(void)
{
}

void __attribute__((noinline))
start_trigger(void)
{
}

void __attribute__((noinline))
stop_trigger(void)
{
}
