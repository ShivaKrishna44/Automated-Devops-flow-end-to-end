1.python approve.py terraform_apply --actor Shiva

Action:  terraform_apply
Effect:  Provision EKS + VPC + ECR + IAM. Creates BILLABLE AWS resources.
Actor:   Shiva

Type the action name 'terraform_apply' to confirm: terraform_apply
Approved 'terraform_apply' as Shiva. Valid for a limited time, single-use.

>>>> Status

======================================================================
  PHASE 1 - KUBECTL: point kubectl at the new cluster (automatic)
======================================================================
kubeconfig -> autoflow-cluster
Updated context arn:aws:eks:us-east-1:589389425618:cluster/autoflow-cluster in C:\Users\Admin\.kube\config

=== NODES ===
NAME                           STATUS   ROLES    AGE   VERSION
ip-10-50-15-126.ec2.internal   Ready    <none>   74s   v1.31.14-eks-3b4a6ca
ip-10-50-23-210.ec2.internal   Ready    <none>   75s   v1.31.14-eks-3b4a6ca



2.python approve.py install_alb_controller --actor shiva

Action:  install_alb_controller
Effect:  Install the AWS Load Balancer Controller (Helm) into the cluster.
Actor:   shiva

Type the action name 'install_alb_controller' to confirm: install_alb_controller
Approved 'install_alb_controller' as shiva. Valid for a limited time, single-use.

>>>> Status :

======================================================================
  PHASE 2 - ALB CONTROLLER: install AWS Load Balancer Controller
======================================================================

[PAUSE] 'install_alb_controller' is a GATED step (destructive/costly).
   In a SECOND terminal, a human runs:
       python approve.py install_alb_controller --actor <your-name>
   Then press Enter here to continue (Ctrl-C to abort).
run.py

$ terraform output -raw cluster_name
autoflow-cluster
$ terraform output -raw alb_controller_role_arn
arn:aws:iam::589389425618:role/autoflow-alb-controller
$ helm repo add eks https://aws.github.io/eks-charts
"eks" already exists with the same configuration, skipping

$ helm repo update
Hang tight while we grab the latest from your chart repositories...
...Successfully got an update from the "eks" chart repository
...Successfully got an update from the "sonarqube" chart repository
...Successfully got an update from the "jenkins" chart repository
...Successfully got an update from the "argo" chart repository
...Successfully got an update from the "prometheus-community" chart repository
Update Complete. ⎈Happy Helming!⎈

$ helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system --set clusterName=autoflow-cluster --set serviceAccount.create=true --set serviceAccount.name=aws-load-balancer-controller --set serviceAccount.annotations.eks\.amazonaws\.com/role-arn=arn:aws:iam::589389425618:role/autoflow-alb-controller
Release "aws-load-balancer-controller" does not exist. Installing it now.
NAME: aws-load-balancer-controller
LAST DEPLOYED: Sat Oct  3 19:54:52 2026
NAMESPACE: kube-system
STATUS: deployed
REVISION: 1
TEST SUITE: None
NOTES:
AWS Load Balancer controller installed!
Release "aws-load-balancer-controller" does not exist. Installing it now.
NAME: aws-load-balancer-controller
LAST DEPLOYED: Sat Oct  3 19:54:52 2026
NAMESPACE: kube-system
STATUS: deployed
REVISION: 1
TEST SUITE: None
NOTES:
AWS Load Balancer controller installed!

======================================================================
  PHASE 3 - CI: GitHub Actions builds & pushes demo-app to ECR
======================================================================

$ terraform output -raw ecr_repository_url
589389425618.dkr.ecr.us-east-1.amazonaws.com/demo-appECR repo: 589389425618.dkr.ecr.us-east-1.amazonaws.com/demo-app
GitHub Actions (ci.yml) builds on push to main and commits the new
image tag into charts/demo-app/values.yaml. Make sure the repo's
Actions Variables are set: AWS_ROLE_ARN, ECR_REGISTRY.
Press Enter once the CI run has succeeded (image in ECR).



4. python approve.py argocd_sync_app --actor shiva

Action:  argocd_sync_app
Effect:  Create the ArgoCD Application and start deploying the app.
Actor:   shiva

Type the action name 'argocd_sync_app' to confirm: argocd_sync_app
Approved 'argocd_sync_app' as shiva. Valid for a limited time, single-use.

>>>>> Status :

======================================================================
  PHASE 4 - DEPLOY: install ArgoCD + apply Application (GitOps)
======================================================================

[PAUSE] 'install_argocd' is a GATED step (destructive/costly).
   In a SECOND terminal, a human runs:
       python approve.py install_argocd --actor <your-name>
   Then press Enter here to continue (Ctrl-C to abort).


$ kubectl apply -f C:\Users\Admin\AppData\Local\Temp\tmpwmmp3sm3.yaml
namespace/argocd created

$ kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io created
customresourcedefinition.apiextensions.k8s.io/appprojects.argoproj.io created
:
:
Waiting for ArgoCD server to come up...

[PAUSE] 'argocd_sync_app' is a GATED step (destructive/costly).
   In a SECOND terminal, a human runs:
       python approve.py argocd_sync_app --actor <your-name>
   Then press Enter here to continue (Ctrl-C to abort).


$ kubectl apply -f C:\Users\Admin\AppData\Local\Temp\tmpq7wdsazp.yaml
application.argoproj.io/demo-app created
application.argoproj.io/demo-app created


Visit https://github.com/prometheus-operator/kube-prometheus for instructions on how to create & configure Alertmanager and Prometheus instances using the Operator.
NAME                                                     READY   STATUS    RESTARTS   AGE
alertmanager-monitoring-kube-prometheus-alertmanager-0   2/2     Running   0          46s
monitoring-grafana-75c999f779-w75jd                      3/3     Running   0          49s
monitoring-kube-prometheus-operator-7986cd78df-rwksn     1/1     Running   0          49s
monitoring-kube-state-metrics-75d7ddcc9c-p46jf           1/1     Running   0          49s
monitoring-prometheus-node-exporter-dtvht                1/1     Running   0          49s
monitoring-prometheus-node-exporter-f529m                1/1     Running   0          49s
prometheus-monitoring-kube-prometheus-prometheus-0       2/2     Running   0          46s



$ kubectl.exe top pods

NAME                       CPU(cores)   MEMORY(bytes)
demo-app-664cc4885-j5rtw   1m           46Mi
demo-app-664cc4885-tb8xw   1m           46Mi

$ kubectl top nodes
NAME                           CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)
ip-10-50-15-126.ec2.internal   98m          5%       1669Mi          50%
ip-10-50-23-210.ec2.internal   68m          3%       1373Mi          41%

$ kubectl.exe get pods -n kube-system -l k8s-app=metrics-server
NAME                             READY   STATUS    RESTARTS   AGE
metrics-server-865f65d7d-pq77k   1/1     Running   0          2m

$ kubectl get hpa
NAME       REFERENCE             TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
demo-app   Deployment/demo-app   cpu: 2%/70%   2         5         2          21m

$ kubectl get applications -n argocd
NAME       SYNC STATUS   HEALTH STATUS
demo-app   Synced        Healthy

Terraform infra → GitHub Actions CI (OIDC) → ECR → ArgoCD GitOps → EKS → app Running & Healthy → HPA autoscaling with real metrics.

Terraform-provisioned EKS infra ✅
GitHub Actions CI building + pushing to ECR via OIDC ✅
ArgoCD GitOps deploying from Git ✅
App running, reachable, and Healthy ✅
HPA autoscaling working with real metrics ✅