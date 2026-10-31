export const artificialSummaryScript = `import csv,json,statistics,math
from pathlib import Path
from openpyxl import Workbook
values=[float(row['value']) for row in csv.DictReader((INPUTS/'input-001.csv').open())]
result={'count':len(values),'sum':math.fsum(values),'mean':statistics.mean(values)}
Path('summary.json').write_text(json.dumps(result))
book=Workbook();sheet=book.active
sheet.append(['count','sum','mean']);sheet.append([result['count'],result['sum'],result['mean']])
book.save('summary.xlsx')
`;
