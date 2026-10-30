"""One report after the entire fixed R1 matrix is accepted; no sequential seed testing."""
import json
from collections import defaultdict
from run_research_case import ROOT,dump
from analyse_research_matrix import paired,holm,write_csv
BATCH=ROOT/'runs/research_v31_primary'
def main():
 receipts=json.loads((BATCH/'r1_accepted_runs.json').read_text());assert len(receipts)==560
 groups=defaultdict(dict)
 for rec in receipts:
  p=rec['params'];assert p['experiment']=='R1_utility'
  d=ROOT/rec['directory'];assert json.loads((d/'offline_validation.json').read_text())['status']=='passed'
  row=json.loads((d/'metrics.json').read_text());k=(p['scenario_id'],p['configuration'],p['model']);assert p['seed'] not in groups[k];groups[k][p['seed']]=row
 for values in groups.values():assert sorted(values)==list(range(1000,1010))
 tests=[]
 for model in ['llama-3.2-1b','llama-3.1-8b']:
  for scenario,metric in [('clean','pdr'),('link_cut','recovery_rmst_s')]:
   tests.append(paired(groups[(scenario,'shielded_heuristic','none')],groups[(scenario,'shielded',model)],metric,{'scenario':scenario,'model':model,'comparison':'shielded LLM minus full-action heuristic'}))
 holm(tests,'p_holm_primary4',n_family=4);out=BATCH/'r1_review';out.mkdir(exist_ok=True);write_csv(out/'primary_contrasts.csv',tests)
 lines=['# R1 đã đủ toàn bộ560 lượt','', 'Đây là kết quả R1 trên đúng10 seed định trước cho mỗi condition. Các khối robustness/ablation/cost/injection bổ sung có thể đang chạy; chưa đánh dấu toàn dự án hoàn tất.','']
 for t in tests:
  if t['status']=='tested':lines.append(f"- {t['model']} / {t['scenario']} / {t['metric']}: LLM trừ heuristic = {t['mean_delta']:.6g} ± {t['delta_ci95']:.6g}, Holm p={t['p_holm_primary4']:.6g}.")
  else:lines.append(f"- {t['model']} / {t['scenario']}: thiếu metric, không kiểm định.")
 lines+=['', 'PDR tăng và RMST giảm là chiều có lợi. Kết quả không có ý nghĩa không chứng minh tương đương. Không thay seed/prompt/guard hoặc dừng các khối còn lại dựa vào dấu hiệu tốt/xấu trong báo cáo này.']
 (out/'R1_REVIEW_VI.md').write_text('\n'.join(lines)+'\n');dump(out/'coverage.json',{'r1_complete':True,'accepted':560,'primary_contrasts':4,'full_project_complete':False})
if __name__=='__main__':main()
