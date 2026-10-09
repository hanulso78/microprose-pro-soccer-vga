/* 호스트 표본 프로파일러: 주 스레드의 RIP 를 1ms 마다 적는다 (hostprof.exe 에 링크) */
#include <windows.h>
#include <stdio.h>
static HANDLE mainth;
static volatile int stop;
static unsigned long long samples[2000000];
static int ns;
static DWORD WINAPI th(LPVOID p)
{
    (void)p;
    timeBeginPeriod(1);
    while (!stop && ns < 2000000) {
        CONTEXT c;
        Sleep(1);
        SuspendThread(mainth);
        c.ContextFlags = CONTEXT_CONTROL;
        if (GetThreadContext(mainth, &c))
            samples[ns++] = c.Rip;
        ResumeThread(mainth);
    }
    return 0;
}
static void dump(void)
{
    FILE *f = fopen("_samples.txt", "w");
    int i;
    stop = 1;
    for (i = 0; i < ns; i++)
        fprintf(f, "%llx\n", samples[i]);
    fclose(f);
}
void sampler_start(void)
{
    DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &mainth, 0, FALSE, DUPLICATE_SAME_ACCESS);
    CreateThread(0, 0, th, 0, 0, 0);
    atexit(dump);
}
