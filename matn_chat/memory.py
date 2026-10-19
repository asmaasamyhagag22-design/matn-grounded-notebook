"""Read-only Linux memory samples and a single L4-unload retry."""
from pathlib import Path
import time

MIN_AVAILABLE=1536*1024**2


def sample_memory(proc=Path('/proc')):
    available=int(next(l.split()[1] for l in (proc/'meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
    runners=[];workers=[]
    for p in proc.glob('[0-9]*'):
        try:
            argv=(p/'cmdline').read_bytes().decode(errors='replace').strip('\0').split('\0')
            runner=(Path(argv[0]).name=='ollama' and argv[1:2]==['runner']) or argv[0]=='/usr/local/lib/ollama/llama-server'
            worker='matn_verification.l4_worker' in argv and '-m' in argv
            if not runner and not worker:continue
            rss=int(next(l.split()[1] for l in (p/'status').read_text().splitlines() if l.startswith('VmRSS:')))*1024
            item={'pid':int(p.name),'rss_bytes':rss}
            (runners if runner else workers).append(item)
        except (OSError,StopIteration,ValueError):continue
    return {'wall':time.time(),'available_bytes':available,'ollama_runner_rss_bytes':sum(x['rss_bytes'] for x in runners),
        'l4_worker_rss_bytes':sum(x['rss_bytes'] for x in workers),'runners':runners,'workers':workers}


class MemoryGuard:
    def __init__(self,*,sample=sample_memory):self.sample=sample;self.samples=[]
    def check(self,unload):
        self.samples=[]
        for attempt in range(2):
            row={**self.sample(),'check':attempt};self.samples.append(row)
            if row['available_bytes']>=MIN_AVAILABLE:return True
            if attempt==0:unload()
        return False
