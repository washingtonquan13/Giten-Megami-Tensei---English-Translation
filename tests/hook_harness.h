/* Harness-side definitions for giten/exe/hook.c: the engine's globals become
 * ordinary variables and the Win32 imports the real functions, so the exact
 * hook logic runs as a native 32-bit exe under the test suite.
 *
 * There is no FILEID here any more.  Overlay v6 identifies no file -- it keys
 * on the CONTENT of the record the program counter is in -- so the engine's
 * current-file global is not something the hook can read even by accident. */
#include <windows.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef DWORD dword;

extern u8 *g_bases[16];
u8 orig_fetch(u32 handle, u16 *pcp);
u32 fake_time(void);            /* the harness's simulated timeGetTime */

#define ORIG_FETCH orig_fetch
#define HANDLE_BASE(h) (g_bases[(h)])
#define pCreateFileA CreateFileA
#define pGetFileSize GetFileSize
#define pReadFile ReadFile
#define pVirtualAlloc VirtualAlloc
#define pCloseHandle CloseHandle
#define pTimeGetTime fake_time
#define pGetModuleHandleA GetModuleHandleA
#define pGetProcAddress(m, n) ((void *)GetProcAddress((m), (n)))
