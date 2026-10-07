import csv
import io
import json

def json_report(result): return json.dumps(result,indent=2,allow_nan=False)

def property_csv(result,run,tier):
    stream=io.StringIO();rows=result['runs'][run]['property_losses'][tier]
    writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        # Spreadsheet formula injection prevention for user-supplied text.
        safe={k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()}
        writer.writerow(safe)
    return stream.getvalue()
