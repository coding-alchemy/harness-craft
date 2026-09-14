"""Evidence-based parent/child ownership; no name/time similarity joins."""


def bind(data):
    sessions = data['sessions']
    events = data.get('events', [])
    starts, identities = {}, {}
    tools = []
    for event in events:
        agent = event.get('agentId')
        parent = event.get('parentSessionId')
        if agent and parent:
            identities[(parent, agent)] = event['session']
            if event['session'] in sessions:
                sessions[event['session']]['parent'] = parent
        if agent and event['event'] in ('subagent.spawned', 'subagent.background.started'):
            starts.setdefault((event['session'], agent), event)
        if agent and event['event'] in ('subagent.completed', 'subagent.background.completed'):
            total = event.get('totalTokens')
            if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                tools.append({'session': event['session'], 'turn': event['turn'], 'agent': agent,
                              'time': event['time'], 'total': total, 'source': event['source']})
    for key, child in identities.items():
        if child in sessions and key in starts:
            sessions[child]['origin_turn'] = starts[key]['turn']
            sessions[child]['parent'] = key[0]
    inherited = []
    kept = []
    by_session = {}
    for record in data['records']:
        if record.get('call_id'):
            by_session.setdefault(record['session'], set()).add(record['call_id'])
    for record in data['records']:
        sid = record['session']; ancestors = set(); cursor = sid
        while cursor in sessions and sessions[cursor].get('forked_from') and not sessions[cursor].get('parent'):
            cursor = sessions[cursor]['forked_from']
            if cursor == sid or cursor in ancestors:
                data['issues'].append({'reason': '分叉继承关系循环，无法验证', 'source': record['sources'][0], 'session': sid})
                break
            ancestors.add(cursor)
        if ancestors and record.get('call_id') and any(record['call_id'] in by_session.get(a,set()) for a in ancestors):
            inherited.append({'session':sid,'call_id':record['call_id'],'sources':record['sources']})
            continue
        if ancestors and record.get('interval_start'):
            data['issues'].append({'reason':'分叉累计区间缺少已验证继承基线；未计入', 'source':record['sources'][0],'session':sid})
            continue
        if ancestors and not all(a in sessions for a in ancestors):
            data['issues'].append({'reason':'祖先来源不可用，无法完整核验继承身份', 'source':record['sources'][0],'session':sid})
        kept.append(record)
    data['records'] = kept
    data['inherited'] = inherited
    for record in data['records']:
        sid = record['session']; current = sid; visited = set(); origin = record.get('root_turn')
        while current in sessions and sessions[current].get('parent'):
            if current in visited:
                data['issues'].append({'reason': '父子关系循环，无法归属', 'source': record['sources'][0], 'session': sid})
                break
            visited.add(current)
            if sessions[current].get('origin_turn'):
                origin = sessions[current]['origin_turn']
            current = sessions[current]['parent']
        record['owner_session'] = current
        record['owner_turn'] = record['turn'] if current == sid else origin
        if current != sid and record['group'] == 'main':
            record['group'] = 'child'
    # Tool totals are an independent channel, never additional usage records.
    unique = {}
    for tool in tools:
        key = (tool['session'], tool['turn'], tool['agent'], tool['time'], tool['total'])
        unique.setdefault(key, tool)
    data['tool_reports'] = list(unique.values())
    return data
