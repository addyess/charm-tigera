# Copyright 2023 pguimaraes
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing


import unittest.mock as mock

import ops.testing
import pytest
from charm import TigeraCharm
from ops.model import WaitingStatus

TEST_CONFIGURE_BGP_INPUT = """- hostname: test
  asn: 1
  interfaces:
  - IP: 20.20.20.20
    peerASN: 20
    peerIP: 30.30.30.30
  rack: r
  stableAddress: 10.10.10.10"""

TEST_CONFIGURE_BGP_BGPLAYOUT_YAML = """apiVersion: projectcalico.org/v3
kind: EarlyNetworkConfiguration
spec:
 nodes:
 - interfaceAddresses:
     - 20.20.20.20
   stableAddress:
     address: 10.10.10.10
   asNumber: 1
   peerings:
     - peerIP: 30.30.30.30
     - peerASN: 20
   labels:
     rack: r"""

TEST_CONFIGURE_BGP_BGPPEER_YAML = """apiVersion: crd.projectcalico.org/v1
kind: BGPPeer
metadata:
  name: r-30.30.30.30
spec:
  peerIP: 30.30.30.30
  asNumber: 20
  nodeSelector: rack == 'r'
  sourceAddress: None
  failureDetectionMode: BFDIfDirectlyConnected
  restartMode: LongLivedGracefulRestart

---
apiVersion: crd.projectcalico.org/v1
kind: BGPConfiguration
metadata:
  name: default
spec:
  nodeToNodeMeshEnabled: false"""

TEST_CONFIGURE_BGP_IPPOOLS_YAML = """apiVersion: crd.projectcalico.org/v1
kind: IPPool
metadata:
  name: default-pool
spec:
  blockSize: 24
  cidr: 192.168.10.0/24
  ipipMode: Always
  nodeSelector: all()
  vxlanMode: Never
---
apiVersion: crd.projectcalico.org/v1
kind: IPPool
metadata:
  name: k8s-nodes-stable-pool
spec:
  cidr: 192.168.1.0/24
  disabled: true
  nodeSelector: all()"""


@pytest.fixture
def harness():
    harness = ops.testing.Harness(TigeraCharm)
    try:
        yield harness
    finally:
        harness.cleanup()


@pytest.fixture
def charm(harness):
    harness.begin_with_initial_hooks()
    yield harness.charm


def test_launch_initial_hooks(charm):
    assert charm.stored.tigera_configured is False, "Unexpected Stored Default"
    assert charm.stored.pod_restart_needed is False, "Unexpected Stored Default"
    assert charm.unit.status == WaitingStatus("Waiting for CNI relation")


@pytest.mark.skip_kubectl_mock
@pytest.mark.usefixtures
@mock.patch("charm.check_output", autospec=True)
def test_kubectl(mock_check_output, charm):
    charm.kubectl("arg1", "arg2")
    mock_check_output.assert_called_with(
        ["kubectl", "--kubeconfig", "/root/.kube/config", "arg1", "arg2"]
    )


@pytest.mark.usefixtures
@mock.patch("jinja2.environment.TemplateStream.dump", autospec=True)
@mock.patch("jinja2.environment.Template.stream", autospec=True)
def test_configure_bgp(mock_stream, mock_dump, charm, harness):
    config_dict = {
        "stable_ip_cidr": "192.168.1.0/24",
        "pod_cidr": "192.168.10.0/24",
        "bgp_parameters": TEST_CONFIGURE_BGP_INPUT,
    }
    harness.update_config(config_dict)
    charm.configure_bgp()
    _, args, _ = mock_stream.mock_calls[0]
    assert args[0].render(bgp_parameters=charm.bgp_parameters) == TEST_CONFIGURE_BGP_BGPLAYOUT_YAML

    _, args, _ = mock_stream.mock_calls[2]
    assert args[0].render(bgp_parameters=charm.bgp_parameters) == TEST_CONFIGURE_BGP_BGPPEER_YAML

    _, args, _ = mock_stream.mock_calls[4]
    assert (
        args[0].render(
            pod_cidr_range=charm.get_ip_range(config_dict["pod_cidr"]),
            pod_cidr=config_dict["pod_cidr"],
            stable_ip_cidr=config_dict["stable_ip_cidr"],
        )
        == TEST_CONFIGURE_BGP_IPPOOLS_YAML
    )
