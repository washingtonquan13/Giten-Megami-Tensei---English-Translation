/* Harness-side definitions for giten/exe/hook.c: the engine's globals become
 * ordinary variables and the Win32 imports the real functions, so the exact
 * hook logic runs as a native 32-bit exe under the test suite. */
#include <windows.h>
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef DWORD dword;

extern u16 g_fileid;
extern u8 *g_bases[16];
u8 orig_fetch(u32 handle, u16 *pcp);

#define ORIG_FETCH orig_fetch
#define FILEID g_fileid
#define HANDLE_BASE(h) (g_bases[(h)])
#define pCreateFileA CreateFileA
#define pGetFileSize GetFileSize
#define pReadFile ReadFile
#define pVirtualAlloc VirtualAlloc
#define pCloseHandle CloseHandle
