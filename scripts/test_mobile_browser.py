"""Real WebKit UI/API software tests in phone/tablet emulation.

Model work is an explicitly blocked software fixture unless --actual-job is
supplied; that flag displays a previously verified real receipt without rerunning it.
This does not establish behavior on physical Apple hardware or a Render URL.
"""
import argparse
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--actual-job')
    parser.add_argument('--browser',choices=('webkit','chromium'),default='webkit')
    args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright, expect
    import uvicorn
    from mobile import api
    token = secrets.token_urlsafe(48)
    os.environ['BENFRANK_API_TOKEN'] = token
    os.environ['BENFRANK_REQUIRE_PERSISTENT_STORAGE'] = 'false'
    reports = []
    with tempfile.TemporaryDirectory() as tmp:
        api.ROOT = Path(tmp)
        def blocked_fixture(config_path, run_dir, state, trials, stress_trials):
            result = {'status': 'SOFTWARE_TEST_FIXTURE_INCOMPLETE', 'props': [],
                'all_requested_props_executed': False, 'preservation_verified': True,
                'fatal_blocker': 'BROWSER_SOFTWARE_TEST_NO_MODEL_RUN'}
            Path(run_dir).mkdir()
            (Path(run_dir) / 'execution_receipt.json').write_text(json.dumps(result))
            return result, 2
        api.run = blocked_fixture
        if args.actual_job:
            actual = Path(args.actual_job).resolve()
            shutil.copytree(actual, api.ROOT / actual.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api.app, host='127.0.0.1', port=port, log_level='error'))
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(.05)
        if not server.started:
            raise RuntimeError('LOCAL_TEST_SERVER_FAILED_TO_START')
        try:
            with sync_playwright() as p:
                browser = p.webkit.launch() if args.browser=='webkit' else p.chromium.launch(executable_path='/usr/bin/chromium')
                for device_name in ('iPhone 13', 'iPad Pro 11'):
                    context = browser.new_context(**p.devices[device_name], timezone_id='America/Los_Angeles', accept_downloads=True)
                    page = context.new_page(); errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto('http://127.0.0.1:' + str(port), wait_until='networkidle')
                    expect(page.get_by_text('Service ready', exact=True)).to_be_visible()
                    width = page.evaluate('({viewport:innerWidth,document:document.documentElement.scrollWidth})')
                    assert width['document'] <= width['viewport'], width
                    page.get_by_label('Private access token', exact=True).fill('incorrect-software-test-token')
                    page.get_by_label('Full player name', exact=True).fill('Example Player')
                    page.get_by_label('Exact line', exact=True).fill('20.5')
                    page.locator('#cutoff').fill('2031-01-01T16:00')
                    page.get_by_role('button', name='Run full framework').click()
                    expect(page.locator('#status')).to_contain_text('UNAUTHORIZED')
                    page.get_by_label('Private access token', exact=True).fill(token)
                    page.get_by_role('button', name='Run full framework').click()
                    expect(page.locator('#status')).to_contain_text('BROWSER_SOFTWARE_TEST_NO_MODEL_RUN', timeout=20000)
                    expect(page.locator('#verified')).to_have_text('Execution unverified')
                    with page.expect_download() as event:
                        page.get_by_role('button', name='Execution receipt').click()
                    downloaded = event.value
                    receipt = json.loads(Path(downloaded.path()).read_text())
                    assert receipt['status'] == 'SOFTWARE_TEST_FIXTURE_INCOMPLETE'
                    with page.expect_download() as event:
                        page.get_by_role('button', name='Evidence ZIP').click()
                    assert Path(event.value.path()).stat().st_size > 0
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#token')).to_have_value('')
                    page.get_by_role('button', name='Check last job').click()
                    expect(page.locator('#status')).to_contain_text('Enter your access token')
                    page.locator('#token').fill(token)
                    page.get_by_role('button', name='Check last job').click()
                    expect(page.locator('#status')).to_contain_text('BROWSER_SOFTWARE_TEST_NO_MODEL_RUN')
                    real_displayed = False
                    if args.actual_job:
                        page.evaluate('(id) => sessionStorage.setItem("benfrank-last-job", id)', actual.name)
                        page.get_by_role('button', name='Check last job').click()
                        expect(page.locator('#verified')).to_have_text('Execution verified ✓')
                        data=json.loads((actual/'job.json').read_text())
                        prediction=json.loads((actual/'execution'/'props'/data['matched_results'][0]['prop']['snapshot_id']/'prediction.json').read_text())
                        expect(page.locator('#direction')).to_have_text(prediction['direction'])
                        assert page.locator('#windows tr').count() == len(prediction['historical_windows'])
                        expect(page.locator('#comparison')).to_contain_text('Model disagreement: '+('YES' if prediction['model_disagreement'] else 'NO'))
                        expect(page.locator('#risk')).to_contain_text('25,000 main trials')
                        real_displayed = True
                    page.locator('#token').fill('')
                    screenshot = output / ('iphone.png' if 'iPhone' in device_name else 'ipad.png')
                    page.screenshot(path=str(screenshot), full_page=True)
                    assert errors == [], errors
                    reports.append({'device': device_name, 'browser': args.browser, 'mode': 'EMULATION_ONLY',
                        'layout_no_horizontal_overflow': True, 'authentication_rejection': True,
                        'job_submission_and_terminal_status': True, 'receipt_and_zip_download': True,
                        'token_not_retained_after_reload': True, 'job_resume': True,
                        'actual_verified_prediction_displayed': real_displayed, 'javascript_errors': errors})
                    context.close()
                browser.close()
        finally:
            server.should_exit = True; thread.join(timeout=10)
    report = {'status': 'PASSED', 'checks': reports, 'render_deployment_tested': False,
              'physical_iphone_or_ipad_tested': False}
    (output / 'browser-test-receipt.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
