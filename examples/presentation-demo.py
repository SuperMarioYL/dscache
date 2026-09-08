import json
from dscache import profile
records=[
 {'request_id':'one','prompt_tokens':100,'cached_tokens':95,'miss_tokens':5,'prefix_sample':'Stable instructions'},
 {'request_id':'two','prompt_tokens':100,'cached_tokens':5,'miss_tokens':95,'prefix_sample':'Stable instructions'},
 {'request_id':'three','prompt_tokens':100}]
for e in profile(records):print(json.dumps({'request':e.request_id,'tier':e.tier.value,'cached':e.cached_tokens,'miss':e.miss_tokens,'busted_against':e.busted_against}))
