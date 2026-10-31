/* Relocatable Mach-O app launcher: no developer interpreter or shell subprocess. */
#include <mach-o/dyld.h>
#include <limits.h>
#include <libgen.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], path[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, path)) return 71;
    char *macos = dirname(path);
    snprintf(python, sizeof(python), "%s/../Resources/python/bin/python3.13", macos);
    snprintf(script, sizeof(script), "%s/../Resources/probe/verify.py", macos);
    char *args[] = {python, "-I", "-B", script, NULL};
    char *env[] = {"PATH=/usr/bin:/bin", "LANG=en_US.UTF-8", "HOME=/var/empty", NULL};
    execve(python, args, env);
    perror("packaged Python boundary failed to start");
    return 72;
}
