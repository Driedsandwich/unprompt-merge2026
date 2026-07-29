import json,os,subprocess,sys,tempfile,time,concurrent.futures as cf
REPO="/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon"
sys.path.insert(0,REPO); import server as S
RAW=open(os.path.join(REPO,"prompts/extraction_product_v1.txt"),encoding="utf-8").read()
A=S.build_extraction_system(RAW)          # 現行 /api/explode(meta 先)
B=S.build_extraction_stream_system(RAW)   # 新 /api/explode_stream(branches 先)
BRIEF=sys.argv[1] if len(sys.argv)>1 else "新機能のリリース告知メールを、堅すぎない感じで書いて。既存ユーザー向け。"
N=int(sys.argv[2]) if len(sys.argv)>2 else 3

def one(tag_i):
    tag,i=tag_i
    sp=A if tag=="A" else B
    wd=tempfile.mkdtemp(); env=os.environ.copy(); env.pop("ANTHROPIC_API_KEY",None)
    r=subprocess.run(["claude","--system-prompt",sp,"--strict-mcp-config","--setting-sources","project",
        "--effort","low","--model","sonnet","--output-format","json","-p","--",BRIEF],
        capture_output=True,text=True,cwd=wd,stdin=subprocess.DEVNULL,env=env,timeout=180)
    try: txt=json.loads(r.stdout).get("result") or ""
    except Exception: txt=""
    ex,why=S.extract_json_object(txt, lambda o: all(k in o for k in S.EXTRACTION_REQUIRED_TOP))
    if ex is None: return (tag,i,"NO_JSON",0,txt[:60].replace("\n"," "))
    pl,_=S.validate_extraction(BRIEF,ex)
    return (tag,i,"ok",len(pl["branches"]),"raw=%d rej=%d"%(pl["branches_returned_by_model"],len(pl["rejected_branches"])))

jobs=[("A",i) for i in range(N)]+[("B",i) for i in range(N)]
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    for res in ex.map(one, jobs):
        print("%s#%d  %-8s branches=%d  %s"%res, flush=True)
